import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwind from '@tailwindcss/vite'

// Production gọi /api cùng origin (Nginx của Gói 4 proxy sang service api).
const proxy = { '/api': process.env.API_URL ?? 'http://localhost:8000' }

// Windows Application Control có thể chặn binary native của Tailwind; bản WASM dự phòng
// không quét được file trên ổ đĩa, nên đưa thẳng token trong JSX cho Tailwind.
// Lưu ý: chỉ đọc khi khởi động, thêm class mới phải restart `npm run dev`.
const tailwindTokens = {
  name: 'tailwind-tokens',
  enforce: 'pre',
  transform(code, id) {
    if (!id.split('?')[0].endsWith('/src/index.css')) return
    const src = join(import.meta.dirname, 'src')
    const tokens = readdirSync(src)
      .filter((f) => f.endsWith('.jsx'))
      .flatMap((f) => readFileSync(join(src, f), 'utf8').match(/[\w:/.[\]%-]+/g) ?? [])
    return `${code}\n@source inline("${[...new Set(tokens)].join(' ')}");\n`
  },
}

export default defineConfig({
  plugins: [tailwindTokens, react(), tailwind()],
  server: { proxy },
  preview: { proxy },
})
