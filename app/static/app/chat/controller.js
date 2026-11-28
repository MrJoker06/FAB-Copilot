(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabChatController = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  function createChatController(deps = {}) {
    const {
      state, $, escapeHtml, api, identityHeaders, FabApiError, apiError, thinkingControl, toolLabels,
      presenter, createConversation, loadSessionLibrary, newClientMessageId, thinkingEffort, chatDraftKey,
      windowImpl = root, documentImpl = root.document, localStorageImpl = root.localStorage,
      fetchImpl = root.fetch, TextDecoderImpl = root.TextDecoder, performanceImpl = root.performance,
      FabSmoothTextBufferImpl = root.FabSmoothTextBuffer,
      FabStreamDiagnosticsImpl = root.FabStreamDiagnostics,
      FabIncrementalMarkdownImpl = root.FabIncrementalMarkdown,
    } = deps;
    const window = windowImpl;
    const document = documentImpl;
    const localStorage = localStorageImpl;
    const fetch = fetchImpl;
    const TextDecoder = TextDecoderImpl;
    const performance = performanceImpl;
    const FabSmoothTextBuffer = FabSmoothTextBufferImpl;
    const FabStreamDiagnostics = FabStreamDiagnosticsImpl;
    const FabIncrementalMarkdown = FabIncrementalMarkdownImpl;
    const { renderMarkdown, renderAssistantInto, addMessage, renderToolFailure } = presenter;
  let attachment = null;
  let selectedSkill = null;

  function setSelectedSkill(skill) {
    selectedSkill = skill;
    const button = $('[data-chat-skill]');
    if (button) {
      button.textContent = skill?.title || '选择技能';
      button.title = skill?.title || '可为本次消息指定技能';
    }
  }

  function bindSkillPicker() {
    const button = $('[data-chat-skill]');
    const dialog = $('[data-chat-skill-dialog]');
    const select = $('[data-chat-skill-select]');
    const status = $('[data-chat-skill-status]');
    button.addEventListener('click', async () => {
      dialog.returnValue = '';
      select.replaceChildren(new root.Option('按意图选择', ''));
      select.disabled = true;
      status.textContent = '正在读取技能目录…';
      dialog.showModal();
      try {
        const {items} = await api('/api/capabilities');
        if (!dialog.open) return;
        const skills = items.filter(item => item.kind === 'skill' && item.chat_executable);
        for (const item of skills) {
          const option = new root.Option(
            (item.title || item.name) + (item.dependencies_ready ? '' : '（依赖未就绪）'), item.name,
          );
          option.disabled = !item.dependencies_ready;
          select.add(option);
        }
        const current = Array.from(select.options).find(option => option.value === selectedSkill?.id && !option.disabled);
        select.value = current?.value || '';
        status.textContent = skills.length ? '' : '当前没有可运行的值班技能。';
      } catch (error) {
        status.textContent = error.message;
      } finally {
        select.disabled = false;
      }
    });
    dialog.addEventListener('close', () => {
      if (dialog.returnValue !== 'apply' || select.disabled) return;
      const option = select.selectedOptions[0];
      setSelectedSkill(option?.value ? {id:option.value, title:option.textContent} : null);
      if (option?.value) clearAnalysisAttachment();
    });
  }
  function renderAttachment() {
    const node = $('#chatAttachment');
    if (!node) return;
    node.hidden = !attachment;
    const label = attachment?.analysisRef ? '共性分析' : '开班检查项';
    node.innerHTML = attachment ? `<span class="chat-attachment-kind">附带${label}</span><span class="chat-attachment-name" title="${escapeHtml(attachment.analysisRef || attachment.dutyCheckRef)}">${escapeHtml(attachment.label)}</span><button type="button" class="chat-attachment-remove" aria-label="移除附带的${label}">移除</button>` : '';
    node.querySelector('.chat-attachment-remove')?.addEventListener('click', clearAnalysisAttachment);
  }
  function attachAnalysis({analysisRef, label, message}) {
    attachReference({analysisRef, label: label || analysisRef}, message);
  }
  function attachDutyCheck({dutyCheckRef, label, message}) {
    attachReference({dutyCheckRef, label: label || dutyCheckRef}, message);
  }
  function attachReference(reference, message) {
    setSelectedSkill(null);
    attachment = reference;
    renderAttachment();
    const input = $('#chatInput');
    input.value = String(message || '').slice(0, input.maxLength > 0 ? input.maxLength : 4000);
    input.dispatchEvent(new root.Event('input', {bubbles:true}));
    input.focus();
  }
  function clearAnalysisAttachment() {
    attachment = null;
    renderAttachment();
  }

  function createLiveAnalysis() {
    const el = document.createElement('div'); el.className = 'message assistant live-analysis';
    el.innerHTML = '<div class="message-meta"><div class="message-label">值班智能助手 · 分析中</div><span class="live-indicator">运行中</span></div><details class="live-path" open><summary><span class="live-path-title">正在建立分析路径</span><small class="live-path-count">准备中</small></summary><div class="live-path-body"><ol></ol><div class="trace-footer"><span>工具调用会在执行时实时更新</span><span class="live-run-id"></span></div></div></details><div class="message-content markdown-content streaming-answer" hidden></div>';
    $('#chatMessages').appendChild(el); $('#chatMessages').scrollTop = $('#chatMessages').scrollHeight;
    const live = {
      el, steps: [], runId: null, buffer: new FabSmoothTextBuffer(), telemetry: new FabStreamDiagnostics(),
      markdownStream: new FabIncrementalMarkdown(), markdownNodes: null,
      renderTimer: null, drainResolvers: [], firstToken: false, cancelled: false,
      renderDelay: 32, lastRenderedText: '', stallTimer: null, visibilityHandler: null, caret: null,
    };
    live.visibilityHandler = () => {
      if (document.hidden || live.cancelled || !live.buffer.pendingLength) return;
      live.telemetry.markVisibleResume();
      if (live.renderTimer) window.clearTimeout(live.renderTimer);
      live.renderTimer = null;
      scheduleLiveAnswerFrame(live, 0);
    };
    document.addEventListener('visibilitychange', live.visibilityHandler);
    return live;
  }

  function renderLiveAnalysis(live) {
    live.el.querySelector('.live-path-title').textContent = live.steps.at(-1)?.label || '正在建立分析路径';
    live.el.querySelector('.live-path-count').textContent = `${live.steps.length} 步`;
    live.el.querySelector('ol').innerHTML = live.steps.map((item, index) => {
      const status = item.status === 'error' ? '失败' : (item.status === 'blocked' ? '已拦截' : (item.status === 'running' ? '进行中' : '完成'));
      const statusClass = item.status === 'error' ? 'error' : (item.status === 'blocked' ? 'blocked' : (item.status === 'running' ? 'running' : 'ok'));
      const result = item.rows == null ? status : `${status} · ${item.rows} 条结果`;
      return `<li><div class="trace-step-heading"><span>${index + 1}. ${escapeHtml(item.label)}</span><small class="trace-status-${statusClass}">${result}</small></div>${renderToolFailure(item)}</li>`;
    }).join('');
    live.el.querySelector('.live-run-id').textContent = live.runId ? `运行 ${live.runId.slice(0, 8)}` : '';
    const container = $('#chatMessages');
    if (container.scrollHeight - container.scrollTop - container.clientHeight < 120) container.scrollTop = container.scrollHeight;
  }

  function startLiveAnswer(live) {
    if (live.firstToken) return;
    live.firstToken = true;
    live.el.querySelector('.live-indicator').textContent = '生成中';
    const running = live.steps.at(-1); if (running?.status === 'running') running.status = 'ok';
    const path = live.el.querySelector('.live-path');
    path.open = false;
    const toolSteps = live.steps.filter(step => step.tool);
    const pathLabel = toolSteps.some(step => step.status === 'error') ? '执行路径异常' : (toolSteps.some(step => step.status === 'blocked') ? '执行路径受限' : '执行路径已完成');
    live.el.querySelector('.live-path-title').textContent = `${pathLabel} · ${toolSteps.length} 个工具`;
    live.el.querySelector('.live-path-count').textContent = '可展开';
    live.el.querySelector('.streaming-answer').hidden = false;
    live.el.querySelector('.streaming-answer').setAttribute('aria-busy', 'true');
    live.el.classList.add('answer-streaming');
  }

  function resolveLiveAnswerDrain(live) {
    if (!live.buffer.done) return;
    for (const resolve of live.drainResolvers.splice(0)) resolve();
  }

  function renderLiveAnswerFrame(live) {
    live.renderTimer = null;
    if (live.cancelled) return;
    const container = $('#chatMessages');
    const follow = container.scrollHeight - container.scrollTop - container.clientHeight < 120;
    const answer = live.el.querySelector('.streaming-answer');
    const renderStarted = performance.now();
    const visible = live.buffer.takeNext({
      targetFrames: live.buffer.complete ? 24 : 14,
      minChars: 2,
      maxChars: live.buffer.complete ? 32 : 24,
    });
    if (visible !== live.lastRenderedText) {
      if (!live.markdownNodes) {
        answer.innerHTML = '<div class="streaming-stable"></div><div class="streaming-tail"></div>';
        live.markdownNodes = {
          stable: answer.querySelector('.streaming-stable'),
          tail: answer.querySelector('.streaming-tail'),
        };
      }
      const patch = live.markdownStream.update(visible);
      live.caret?.remove();
      if (patch.reset) live.markdownNodes.stable.replaceChildren();
      if (patch.stableDelta) {
        live.markdownNodes.stable.insertAdjacentHTML('beforeend', renderMarkdown(patch.stableDelta));
      }
      live.markdownNodes.tail.innerHTML = renderMarkdown(patch.presentableTail);
      const caretTarget = live.markdownNodes.tail.lastElementChild || live.markdownNodes.stable.lastElementChild;
      if (caretTarget) {
        live.caret = document.createElement('span');
        live.caret.className = 'streaming-caret';
        live.caret.setAttribute('aria-hidden', 'true');
        caretTarget.appendChild(live.caret);
      }
      const visibleStep = patch.reset ? visible.length : visible.length - live.lastRenderedText.length;
      live.telemetry.markIncrementalRender(patch.stableDelta.length, patch.tail.length, visibleStep, patch.reset);
      live.lastRenderedText = visible;
    }
    const renderDuration = performance.now() - renderStarted;
    live.telemetry.markRender(renderDuration);
    live.renderDelay = Math.min(80, Math.max(28, renderDuration * 3));
    if (follow) container.scrollTop = container.scrollHeight;
    if (live.buffer.pendingLength) {
      live.renderTimer = window.setTimeout(() => renderLiveAnswerFrame(live), live.renderDelay);
    } else {
      resolveLiveAnswerDrain(live);
    }
  }

  function scheduleLiveAnswerFrame(live, delay = live.renderDelay) {
    if (live.cancelled || live.renderTimer || !live.buffer.pendingLength) return;
    live.renderTimer = window.setTimeout(() => renderLiveAnswerFrame(live), delay);
  }

  function armLiveAnswerStall(live) {
    if (live.stallTimer) window.clearTimeout(live.stallTimer);
    live.el.querySelector('.live-indicator').textContent = '生成中';
    live.stallTimer = window.setTimeout(() => {
      if (!live.cancelled && live.firstToken && !live.buffer.complete) {
        live.el.querySelector('.live-indicator').textContent = '模型继续生成中';
      }
    }, 1500);
  }

  function appendLiveAnswer(live, delta) {
    if (!delta || live.cancelled) return;
    live.buffer.append(delta);
    live.telemetry.markPending(live.buffer.pendingLength);
    if (!live.firstToken) {
      startLiveAnswer(live);
    }
    armLiveAnswerStall(live);
    scheduleLiveAnswerFrame(live);
  }

  async function finishLiveAnswer(live, finalAnswer) {
    live.buffer.finish(finalAnswer);
    live.telemetry.markPending(live.buffer.pendingLength);
    if (live.buffer.received && !live.firstToken) startLiveAnswer(live);
    live.el.querySelector('.live-indicator').textContent = live.buffer.done ? '完成' : '输出中';
    if (live.stallTimer) window.clearTimeout(live.stallTimer);
    live.stallTimer = null;
    scheduleLiveAnswerFrame(live, 0);
    if (!live.buffer.done) await new Promise(resolve => live.drainResolvers.push(resolve));
    live.el.querySelector('.streaming-answer').setAttribute('aria-busy', 'false');
    document.removeEventListener('visibilitychange', live.visibilityHandler);
  }

  function cancelLiveAnswer(live) {
    live.cancelled = true;
    if (live.renderTimer) window.clearTimeout(live.renderTimer);
    if (live.stallTimer) window.clearTimeout(live.stallTimer);
    live.renderTimer = null;
    live.stallTimer = null;
    document.removeEventListener('visibilitychange', live.visibilityHandler);
    for (const resolve of live.drainResolvers.splice(0)) resolve();
  }

  function updateLiveAnalysis(live, event) {
    if (event.event === 'run_started') {
      live.runId = event.run_id;
      live.steps.push({label:'建立分析任务', status:'ok'});
    } else if (event.event === 'stage') {
      const previous = live.steps.at(-1); if (previous?.status === 'running') previous.status = 'ok';
      live.steps.push({label:event.message || '规划下一步', status:'running'});
    } else if (event.event === 'tool_started') {
      const previous = live.steps.at(-1); if (previous?.status === 'running') previous.status = 'ok';
      live.steps.push({tool:event.tool, label:toolLabels[event.tool] || event.tool, status:'running'});
    } else if (event.event === 'tool_finished') {
      const item = [...live.steps].reverse().find(step => step.tool === event.tool && step.status === 'running');
      if (item) Object.assign(item, {status:event.status || 'ok', rows:event.rows, error:event.error, error_code:event.error_code, user_message:event.user_message, recovery_action:event.recovery_action, retryable:event.retryable, execution_state:event.execution_state});
    } else if (event.event === 'tool_result_access') {
      if (!live.steps.some(item => item.resultCallId === event.notice?.call_id)) live.steps.push({resultCallId:event.notice?.call_id, label:event.notice?.message || '工具结果内容状态已更新', status:event.notice?.status === 'saved' ? 'ok' : 'blocked'});
    } else if (event.event === 'run_failed') {
      live.steps.push({label:event.message || '分析失败', status:'error'});
      live.el.querySelector('.live-path').open = true;
    } else if (event.event === 'answer_delta') {
      appendLiveAnswer(live, event.delta);
      return;
    }
    renderLiveAnalysis(live);
  }

  async function streamAgent(message, clientMessageId, onProgress, diagnostics, effort = 'off', resultRef = null, resultCursor = null, analysisRef = null, skillId = null, dutyCheckRef = null) {
    let response;
    try {
      const payload = thinkingControl.requestPayload({message, session_id:state.sessionId, client_message_id:clientMessageId}, state.modelConfig, effort);
      if (resultRef) Object.assign(payload, {tool_result_ref:resultRef, tool_result_cursor:resultCursor});
      else if (analysisRef) payload.analysis_ref = analysisRef;
      else if (skillId) payload.skill_id = skillId;
      else if (dutyCheckRef) payload.duty_check_ref = dutyCheckRef;
      const headers = identityHeaders({'Content-Type':'application/json'});
      response = await fetch('/api/chat/stream', {method:'POST', headers, body:JSON.stringify(payload)});
    } catch {
      throw new FabApiError('无法连接 Fab Insight 服务', {code:'NETWORK_ERROR', retryable:true});
    }
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw apiError(payload, response);
    }
    if (!response.body) throw new FabApiError('浏览器不支持流式响应', {code:'STREAM_UNSUPPORTED'});
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = '', finalResult = null;
    while (true) {
      const {value, done} = await reader.read();
      if (value?.length) diagnostics.markRead();
      buffer += decoder.decode(value || new Uint8Array(), {stream:!done});
      const lines = buffer.split('\n'); buffer = lines.pop() || '';
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === 'session') {
          state.sessionId = event.session_id; localStorage.setItem('fabInsightSessionId', state.sessionId);
        } else if (event.type === 'progress') {
          diagnostics.markProgress(event);
          onProgress(event);
        }
        else if (event.type === 'result') finalResult = event.result;
        else if (event.type === 'error') throw apiError(event.error || {detail:event.detail || '分析失败'}, response);
      }
      if (done) break;
    }
    if (!finalResult) throw new FabApiError('分析结束但未收到结果', {code:'STREAM_INCOMPLETE', requestId:response.headers.get('x-request-id') || '', retryable:true});
    return finalResult;
  }

  function reportStreamTelemetry(live, finalAnswer) {
    const payload = live.telemetry.finish(live.buffer.received === String(finalAnswer || ''));
    if (!payload.run_id) return;
    fetch('/api/telemetry/stream', {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload), keepalive: true,
    }).catch(() => {});
  }

  function renderAgentRequestError(live, error, retry) {
    const labels = {
      MODEL_UPSTREAM_ERROR: '模型服务暂时不可用',
      MODEL_NETWORK_ERROR: '模型服务连接失败',
      NETWORK_ERROR: 'Fab Insight 服务连接失败',
      SESSION_NOT_FOUND: '当前会话已经失效',
    };
    const title = labels[error.code] || '分析请求未完成';
    const technical = [error.code, error.requestId ? `请求 ${error.requestId}` : ''].filter(Boolean).join(' · ');
    const answer = live.el.querySelector('.streaming-answer');
    live.el.classList.remove('answer-streaming');
    answer.hidden = false;
    answer.innerHTML = `<div class="request-error"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(error.message)}</span><div class="request-error-actions">${error.retryable ? '<button type="button" class="retry-request">重试</button>' : ''}<details><summary>错误详情</summary><code>${escapeHtml(technical || '无请求编号')}</code></details></div></div>`;
    answer.querySelector('.retry-request')?.addEventListener('click', retry);
    live.el.querySelector('.live-indicator').textContent = '失败';
  }

  async function sendChat(message, {clientMessageId = newClientMessageId(), isRetry = false, effort = thinkingEffort(), resultRef = null, resultCursor = null, analysisRef = null, skillId = null, dutyCheckRef = null} = {}) {
    const text = message.trim(); if (!text || state.streaming) return;
    if (!state.sessionId) await createConversation();
    $('.suggestions')?.remove();
    if (!isRetry) {
      if (!resultRef && attachment) {
        analysisRef = attachment.analysisRef || null;
        dutyCheckRef = attachment.dutyCheckRef || null;
        clearAnalysisAttachment();
      }
      if (!resultRef && !analysisRef && !dutyCheckRef && selectedSkill) {
        skillId = selectedSkill.id;
        setSelectedSkill(null);
      }
      addMessage('user', text, analysisRef ? {analysis_ref:analysisRef} : {}); state.history.push({role:'user', content:text});
      $('#chatInput').value = '';
      localStorage.removeItem(chatDraftKey);
    }
    $('#sendButton').disabled = true; state.streaming = true;
    const live = createLiveAnalysis();
    try {
      const result = await streamAgent(text, clientMessageId, event => updateLiveAnalysis(live, event), live.telemetry, effort, resultRef, resultCursor, analysisRef, skillId, dutyCheckRef);
      await finishLiveAnswer(live, result.answer);
      reportStreamTelemetry(live, result.answer);
      renderAssistantInto(live.el, result.answer, result);
      state.history.push({role:'assistant', content:result.answer});
      $('#agentMode').textContent = result.mode === 'snapshot_review' ? '已保存结果查看' : (result.mode === 'deepseek' ? `${state.modelConfig?.model || 'DeepSeek'} · 工具分析` : '本地规则分析');
    } catch (error) {
      cancelLiveAnswer(live);
      updateLiveAnalysis(live, {event:'run_failed', message:error.message});
      renderAgentRequestError(live, error, () => {
        live.el.remove();
        sendChat(text, {clientMessageId, isRetry:true, effort, resultRef, resultCursor, analysisRef, skillId, dutyCheckRef});
      });
    }
    finally {
      state.streaming = false; $('#sendButton').disabled = false; $('#chatInput').focus();
      if ($('#sessionsView').classList.contains('active')) loadSessionLibrary().catch(() => {});
    }
  }


    return {
      createLiveAnalysis, renderLiveAnalysis, startLiveAnswer, resolveLiveAnswerDrain,
      renderLiveAnswerFrame, scheduleLiveAnswerFrame, armLiveAnswerStall, appendLiveAnswer,
      finishLiveAnswer, cancelLiveAnswer, updateLiveAnalysis, streamAgent, reportStreamTelemetry,
      renderAgentRequestError, sendChat, attachAnalysis, attachDutyCheck, clearAnalysisAttachment, bindSkillPicker,
    };
  }

  return { createChatController };
});
