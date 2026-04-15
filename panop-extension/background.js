const DEFAULT_API_URL = "http://127.0.0.1:8000";

// Scan every 12 hours (720 minutes) as requested
chrome.alarms.create("scanTabs", { periodInMinutes: 720 });

chrome.alarms.onAlarm.addListener(async (alarm) => {
    if (alarm.name === "scanTabs") {
        console.log("Starting 12-hour sync batch...");
        
        // 1. Scan Local Desktop Tabs
        const localTabs = await chrome.tabs.query({});
        for (const tab of localTabs) {
            await sendToBackend(tab);
        }

        // 2. Scan Remote/Android Synced Tabs
        chrome.sessions.getDevices(async (devices) => {
            for (const device of devices) {
                // This fetches ALL open tabs synced to Chrome currently on that device
                for (const session of device.sessions) {
                    if (session.window && session.window.tabs) {
                        for (const tab of session.window.tabs) {
                            await sendToBackend(tab);
                        }
                    } else if (session.tab) {
                        await sendToBackend(session.tab);
                    }
                }
            }
        });
    }
});

async function sendToBackend(tab) {
    if (!tab.url) return;
    if (tab.url.startsWith("chrome://")) return;
    
    // We send EVERYTHING to the local backend. The backend strictly applies the GUI's rules
    // and checks if it's already cataloged so the Extension remains dumb and lightweight.
    try {
        const data = await chrome.storage.sync.get(['apiUrl', 'apiKey']);
        const apiUrl = data.apiUrl || DEFAULT_API_URL;
        
        const response = await fetch(`${apiUrl}/api/v1/process-tab`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${data.apiKey || ''}`
            },
            body: JSON.stringify({
                url: tab.url,
                title: tab.title,
                timestamp: new Date().toISOString(),
                is_pdf: tab.url.toLowerCase().split('?')[0].endsWith('.pdf')
            })
        });

        if (!response.ok) {
            console.error("Backend error for", tab.url);
        }
    } catch (e) {
        console.error("Failed to reach Panop Server for:", tab.url, e);
    }
}
