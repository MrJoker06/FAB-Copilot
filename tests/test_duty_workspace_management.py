import asyncio
import json
import os
import secrets
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated
from unittest.mock import patch

import httpx
from fastapi import FastAPI, Header, HTTPException

from app.api.dependencies import AuthenticationDependencies, current_admin
from app.api.report_directory import create_router as report_router
from app.api.routers.shared_documents import create_router as document_router
from app.core.identity import PrincipalContextMiddleware, current_principal
from app.knowledge import shared_documents


class DutyWorkspaceManagementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / 'report_directory.json'
        self.document_root = self.root / 'shared'
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {'FAB_REPORT_DIRECTORY_PATH':str(self.directory), 'FAB_SHARED_DOCUMENTS_ROOT':str(self.document_root), 'FAB_REQUIRE_IDENTITY':'false'}).start()
        self.admin_headers = {'Authorization':'Bearer test-admin'}
        self.first = {'X-Tenant-ID':'company','X-User-ID':'alice'}
        self.second = {'X-Tenant-ID':'company','X-User-ID':'bob'}
        self.model_config = self.root / 'local_models.json'
        self.model_config.write_text('{"models":{"company-qwen":{"provider_model":"qwen-test","thinking":true}}}\n',encoding='utf-8')
        self.model_before = self.model_config.read_bytes()
        self.app = self.make_app()

    def make_app(self):
        app = FastAPI()
        app.add_middleware(PrincipalContextMiddleware)
        dependencies = AuthenticationDependencies(get_settings=lambda:SimpleNamespace(admin_api_token='test-admin'), current_principal=current_principal, compare_digest=secrets.compare_digest, http_problem=lambda status,code,message,retry:HTTPException(status,detail={'error_code':code,'message':message,'retryable':retry}))

        def admin(authorization: Annotated[str | None, Header()] = None):
            return current_admin(authorization, deps=dependencies)

        def user():
            return current_principal().knowledge_owner_id

        runtime = {'current_principal':current_principal, 'get_settings':lambda:SimpleNamespace(personal_knowledge_max_upload_bytes=1024),
            'personal_problem':lambda exc:HTTPException(exc.status_code,detail={'error_code':exc.error_code,'message':exc.detail}),
            'http_problem':dependencies.http_problem}
        app.include_router(report_router(admin).router)
        app.include_router(document_router(lambda:runtime,user,admin).router)
        return app

    def run_async(self, operation):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://test') as client:
                await operation(client)
        asyncio.run(run())
        self.assertEqual(self.model_config.read_bytes(), self.model_before)

    def test_report_folder_roundtrip_visibility_revision_and_model_preservation(self):
        async def run(client):
            for headers in ({}, {'X-Roles':'admin'}, {'Authorization':'Bearer wrong'}):
                self.assertEqual((await client.get('/api/admin/report-directory',headers=headers)).status_code,401)
            payload={'revision':0,'folders':[{'id':'engineering','name':'工程','parent_id':None},{'id':'spc','name':'SPC','parent_id':'engineering'}],
                'reports':[{'id':'second','title':'后展示','url':'https://example.org/report','sort_order':20,'folder_id':'spc'},
                           {'id':'first','title':'先展示','url':'/display_mock_data/reports/spc.html','sort_order':10},
                           {'id':'hidden','title':'停用报表','url':'/hidden','enabled':False}]}
            denied=await client.put('/api/admin/report-directory',json=payload,headers={'X-Roles':'admin'})
            self.assertEqual(denied.status_code,401)
            self.assertFalse(self.directory.exists())
            response=await client.put('/api/admin/report-directory',json=payload,headers=self.admin_headers)
            self.assertEqual(response.status_code,200,response.text)
            saved=response.json(); self.assertEqual(saved['revision'],1)
            self.assertEqual(json.loads(self.directory.read_text(encoding="utf-8")), saved)
            public=(await client.get('/api/reports/directory')).json()
            self.assertEqual([item['id'] for item in public['reports']],['first','second'])
            self.assertNotIn('folders',public)
            self.assertNotIn('folder_id',public['reports'][1])
            self.assertEqual((await client.put('/api/admin/report-directory',json=payload,headers=self.admin_headers)).status_code,409)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.make_app()),base_url='http://restart') as restarted:
                self.assertEqual((await restarted.get('/api/admin/report-directory',headers=self.admin_headers)).json(),saved)
        self.run_async(run)

    def test_report_url_and_folder_rejections_do_not_persist(self):
        async def run(client):
            for url in ('javascript:alert(1)','//evil.example/report','https://user:secret@example.org/','/\\evil','https://example.org:bad/'):
                payload={'reports':[{'id':'r','title':'报表','url':url}]}
                response=await client.put('/api/admin/report-directory',json=payload,headers=self.admin_headers)
                self.assertEqual(response.status_code,422,(url,response.text))
            for folders in ([{'id':'a','name':'A','parent_id':'b'},{'id':'b','name':'B','parent_id':'a'}], [{'id':'a','name':'A','parent_id':'missing'}]):
                response=await client.put('/api/admin/report-directory',json={'folders':folders},headers=self.admin_headers)
                self.assertEqual(response.status_code,422)
            self.assertFalse(self.directory.exists())
        self.run_async(run)

    def test_corrupt_saved_directory_is_not_replaced_by_display_defaults(self):
        self.directory.write_text('{broken',encoding='utf-8')
        async def run(client):
            for url,headers in [('/api/reports/directory',{}),('/api/admin/report-directory',self.admin_headers)]:
                response=await client.get(url,headers=headers)
                self.assertEqual(response.status_code,503)
                self.assertNotIn(str(self.root),response.text)
            self.assertEqual(self.directory.read_text(),'{broken')
        self.run_async(run)

    def test_real_upload_shared_read_edit_disable_and_download(self):
        content='# 值班复核 SOP\n\n核对批次、设备状态与维护时间，再记录复核结论。\n'.encode()
        async def run(client):
            response=await client.post('/api/knowledge/shared/documents',headers=self.first,files={'file':('shift.md',content,'text/markdown')},data={'kind':'case','title':'交接记录','process':'CVD'})
            self.assertEqual(response.status_code,202,response.text)
            document_id=response.json()['document_id']; endpoint=f'/api/knowledge/shared/documents/{document_id}'
            public=(await client.get('/api/knowledge/shared/documents',headers=self.second)).json()['items']
            self.assertEqual([item['title'] for item in public],['交接记录'])
            self.assertFalse(public[0]['own'])
            self.assertIn('核对批次',(await client.get(endpoint,headers=self.second)).text)
            self.assertEqual((await client.get(endpoint+'/file',headers=self.second)).content,content)
            body={'title':'共享 SOP','kind':'sop','process':'ETCH','enabled':False}
            self.assertEqual((await client.patch('/api/admin/shared-documents/'+document_id,json=body,headers={'X-Roles':'admin'})).status_code,401)
            changed=await client.patch('/api/admin/shared-documents/'+document_id,json=body,headers=self.admin_headers)
            self.assertEqual(changed.status_code,200,changed.text)
            for identity in (self.first,self.second):
                self.assertEqual((await client.get(endpoint,headers=identity)).status_code,404)
                self.assertEqual((await client.get(endpoint+'/file',headers=identity)).status_code,404)
            self.assertEqual((await client.get('/api/knowledge/shared/documents',headers=self.second)).json()['items'],[])
            admin=(await client.get('/api/admin/shared-documents/'+document_id,headers=self.admin_headers)).json()
            self.assertEqual(admin['kind'],'sop'); self.assertIn('核对批次',json.dumps(admin,ensure_ascii=False))
            body['enabled']=True
            await client.patch('/api/admin/shared-documents/'+document_id,json=body,headers=self.admin_headers)
            self.assertEqual((await client.get(endpoint,headers=self.second)).json()['title'],'共享 SOP')
        self.run_async(run)

    def test_invalid_upload_and_failed_parse_are_not_shared(self):
        async def run(client):
            for name,content,status in [('run.exe',b'executable',415),('bad.md',b'\x00bad',422),('large.txt',b'x'*1025,413)]:
                response=await client.post('/api/knowledge/shared/documents',headers=self.first,files={'file':(name,content)},data={'kind':'sop'})
                self.assertEqual(response.status_code,status,response.text)
            invalid=await client.post('/api/knowledge/shared/documents',headers=self.first,files={'file':('ok.txt',b'ok')},data={'kind':'sop','process':'INVALID'})
            self.assertEqual(invalid.status_code,422)
            response=await client.post('/api/knowledge/shared/documents',headers=self.first,files={'file':('empty.txt',b'   \n')},data={'kind':'case'})
            document_id=response.json()['document_id']
            own=(await client.get('/api/knowledge/shared/documents',headers=self.first)).json()['items']
            self.assertEqual(own[0]['status'],'failed'); self.assertTrue(own[0]['error_message'])
            self.assertEqual((await client.get('/api/knowledge/shared/documents',headers=self.second)).json()['items'],[])
            self.assertEqual((await client.get('/api/knowledge/shared/documents/'+document_id,headers=self.second)).status_code,404)
        self.run_async(run)

    def test_interrupted_processing_resumes_and_keeps_disabled_visibility(self):
        principal=SimpleNamespace(tenant_id='company',user_id='alice')
        document_id=shared_documents.create_upload(principal,'sop.txt','设备报警复核步骤与交接记录'.encode(),'sop','复核','',storage_root=self.document_root)
        shared_documents.update_document(document_id,{'enabled':False},storage_root=self.document_root)
        shared_documents.resume_pending(storage_root=self.document_root)
        detail=shared_documents.get_document(document_id,admin=True,storage_root=self.document_root)[0]
        self.assertEqual(detail['status'],'ready'); self.assertFalse(detail['enabled'])
        self.assertIn('设备报警',detail['sections'][0]['text'])
        self.assertEqual(shared_documents.list_documents(SimpleNamespace(tenant_id='company',user_id='bob'),storage_root=self.document_root),[])


if __name__ == '__main__':
    unittest.main()
