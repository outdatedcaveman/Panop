const { app, BrowserWindow, ipcMain, shell } = require('electron')
const path = require('path')
const { spawn } = require('child_process')

let backendProcess = null;

function createWindow () {
  const win = new BrowserWindow({
    width: 900,
    height: 700,
    backgroundColor: '#0f172a',
    icon: path.join(__dirname, 'panop.ico'),
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  })

  // Disable default menu
  win.setMenu(null);
  
  win.loadFile('index.html')
}

ipcMain.on('open-local-path', (event, targetPath) => {
    shell.openPath(targetPath);
});

app.whenReady().then(() => {
  // Launch the backend invisibly!
  let backendPath;
  const isPackaged = __dirname.includes('app.asar') || __dirname.includes('resources');
  
  if (isPackaged) {
      backendPath = path.join(__dirname, 'panop-server.exe');
  } else {
      backendPath = path.join(__dirname, '..', 'panop-server', 'dist', 'panop-server.exe');
  }

  try {
      backendProcess = spawn(backendPath, [], { windowsHide: true });
  } catch (err) {
      console.log("Could not start backend automatically. Please start it manually.");
  }

  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (backendProcess) {
      backendProcess.kill();
  }
  if (process.platform !== 'darwin') app.quit()
})
