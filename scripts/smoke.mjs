// Дымовой тест в настоящем браузере: открывает приложение, собирает детали,
// проверяет DOM и снимает скриншот. Запуск: node scripts/smoke.mjs [url]
import puppeteer from 'puppeteer-core'
import { existsSync, writeFileSync } from 'node:fs'

const url = process.argv[2] || 'http://localhost:5173/'

// Chromium ищем по очереди: сначала бандл @sparticuz/chromium (Linux/CI),
// потом обычные установки Chrome на macOS/Windows/Linux.
async function findChromium() {
  if (process.env.CHROME_PATH) return { exe: process.env.CHROME_PATH, args: [] }
  const candidates = [
    process.platform === 'darwin' ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : null,
    process.platform === 'win32' ? 'C:/Program Files/Google/Chrome/Application/chrome.exe' : null,
    process.platform === 'win32' ? 'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe' : null,
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
  ].filter(Boolean)
  for (const c of candidates) if (existsSync(c)) return { exe: c, args: [] }
  const mod = await import('@sparticuz/chromium').catch(() => null)
  if (mod) return { exe: await mod.default.executablePath(), args: [...mod.default.args, '--single-process', '--no-zygote'] }
  throw new Error('Не найден Chrome. Укажите CHROME_PATH или установите @sparticuz/chromium.')
}

const { exe, args } = await findChromium()
console.log('chromium:', exe)

const browser = await puppeteer.launch({ args, executablePath: exe, headless: true, timeout: 30000 })

const page = await browser.newPage()
await page.setViewport({ width: 1440, height: 900 })
const errors = []
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(`console: ${m.text()}`)
})
page.on('requestfailed', (r) => errors.push(`request failed: ${r.url()} ${r.failure()?.errorText}`))

await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 })
await new Promise((r) => setTimeout(r, 3500))

const probe = () =>
  page.evaluate(() => ({
    verdict: document.querySelector('#verdict')?.textContent?.trim() ?? '',
    report: document.querySelector('#report')?.textContent?.replace(/\s+/g, ' ').trim() ?? '',
    folds: document.querySelectorAll('#folds .fold-row').length,
    netPolys: document.querySelectorAll('#netHost svg polygon').length,
    netLines: document.querySelectorAll('#netHost svg line').length,
    canvas: !!document.querySelector('#threeHost canvas'),
    canvasSize: (() => {
      const c = document.querySelector('#threeHost canvas')
      return c ? `${c.width}×${c.height}` : 'нет'
    })(),
    status: document.querySelector('#status')?.textContent?.replace(/\s+/g, ' ').trim() ?? '',
    badges: [...document.querySelectorAll('#report .r-badge')].map((b) => b.textContent?.trim()),
  }))

const first = await probe()
console.log('стартовое состояние:', JSON.stringify(first, null, 2))
await page.screenshot({ path: 'tmp/shot-start.png' })

// перебор примеров через поле запроса
const prompts = [
  'лоток 180x120x40',
  'труба 120x200 24 гран',
  'воронка 160x40x120 24 гран',
  'пирамида 4 120 140',
  'уголок 50x50 длина 400',
  'коробка 200x150x100 с крышкой',
]
for (const prompt of prompts) {
  await page.evaluate((p) => {
    const ta = document.querySelector('#prompt')
    ta.value = p
    document.querySelector('#build').click()
  }, prompt)
  await new Promise((r) => setTimeout(r, 700))
  const s = await probe()
  console.log(`\n${prompt}\n  ${s.status}\n  ${s.report.slice(0, 120)}\n  панелей ${s.folds}, полигонов ${s.netPolys}`)
}

// скриншот финального состояния + «разложенный» вид
await page.screenshot({ path: 'tmp/shot-box.png' })
await page.evaluate(() => {
  const s = document.querySelector('#fold')
  s.value = '0'
  s.dispatchEvent(new Event('input', { bubbles: true }))
})
await new Promise((r) => setTimeout(r, 500))
await page.screenshot({ path: 'tmp/shot-flat.png' })

// ошибка разбора
await page.evaluate(() => {
  const ta = document.querySelector('#prompt')
  ta.value = 'сделай красиво'
  document.querySelector('#build').click()
})
await new Promise((r) => setTimeout(r, 300))
console.log('\nошибка разбора:', await page.evaluate(() => document.querySelector('#verdict')?.textContent?.trim()))

console.log('\nошибки в консоли:', errors.length ? errors : 'нет')
writeFileSync('tmp/smoke-errors.json', JSON.stringify(errors, null, 2))
await browser.close()
if (errors.length) process.exitCode = 1
