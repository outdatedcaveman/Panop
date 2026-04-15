const { app, BrowserWindow, ipcMain, shell } = require('electron')
const path = require('path')

function createWindow () {
  const win = new BrowserWindow({
    width: 900,
    height: 700,
    backgroundColor: '#0f172a',
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  })

  // Disable default menu
  win.setMenu(null);
  
  win.loadFile('index.html')
}

ipcMain.on('open-folder', (event, targetFolder) => {
    let targetPath;
    if (targetFolder === 'RIS' || targetFolder === 'ARTICLES' || targetFolder === 'BOOKS') {
        const outDir = targetFolder === 'RIS' ? 'ris' : (targetFolder === 'ARTICLES' ? 'Android Articles' : 'Android Books');
        targetPath = path.join(__dirname, '..', 'panop-server', 'panop_output', outDir);
    } else {
        targetPath = path.join(__dirname, '..', 'panop-server', 'panop_output');
    }
    shell.openPath(targetPath);
});

app.whenReady().then(() => {
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
