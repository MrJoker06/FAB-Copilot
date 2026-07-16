import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider, theme } from 'antd'
import { BrowserRouter } from 'react-router-dom'

import App from './App'
import './styles.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: '#087f70',
          colorInfo: '#087f70',
          colorSuccess: '#2f7d4d',
          colorWarning: '#b87917',
          colorError: '#c95445',
          colorText: '#17211f',
          colorTextSecondary: '#697572',
          colorBorder: '#dce3e1',
          colorBgBase: '#ffffff',
          colorBgLayout: '#f4f6f7',
          borderRadius: 5,
          fontSize: 12,
          fontFamily: "Inter, 'Segoe UI', 'Microsoft YaHei', sans-serif",
        },
      }}
    >
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </ConfigProvider>
  </React.StrictMode>,
)
