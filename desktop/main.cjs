// Оболочка для ПК: обычное окно с тем же интерфейсом, что и в браузере.
const { app, BrowserWindow, Menu, shell, dialog } = require('electron')
const path = require('node:path')
const fs = require('node:fs')

const DEV_URL = process.env.SGIB_DEV_URL || ''

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 680,
    backgroundColor: '#0d0f13',
    title: 'Сгиб',
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  win.once('ready-to-show', () => win.show())

  if (DEV_URL) {
    win.loadURL(DEV_URL)
  } else {
    const index = path.join(__dirname, '..', 'dist', 'index.html')
    if (!fs.existsSync(index)) {
      dialog.showErrorBox(
        'Не собрано',
        'Сначала соберите интерфейс: npm run build',
      )
      app.quit()
      return
    }
    win.loadFile(index)
  }

  // Внешние ссылки — в системный браузер, окно приложения не уводим.
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })
}

const menu = Menu.buildFromTemplate([
  {
    label: 'Файл',
    submenu: [{ role: 'quit', label: 'Выход' }],
  },
  {
    label: 'Вид',
    submenu: [
      { role: 'reload', label: 'Обновить' },
      { role: 'toggleDevTools', label: 'Инструменты' },
      { type: 'separator' },
      { role: 'resetZoom', label: 'Обычный масштаб' },
      { role: 'zoomIn', label: 'Крупнее' },
      { role: 'zoomOut', label: 'Мельче' },
      { type: 'separator' },
      { role: 'togglefullscreen', label: 'Во весь экран' },
    ],
  },
])

app.whenReady().then(() => {
  Menu.setApplicationMenu(menu)
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
