document.addEventListener('DOMContentLoaded', () => {
    // Load existing settings
    chrome.storage.sync.get(['apiUrl', 'apiKey', 'autoClose'], (items) => {
        if (items.apiUrl) document.getElementById('apiUrl').value = items.apiUrl;
        if (items.apiKey) document.getElementById('apiKey').value = items.apiKey;
        if (items.autoClose !== undefined) document.getElementById('autoClose').checked = items.autoClose;
    });

    // Save settings
    document.getElementById('saveBtn').addEventListener('click', () => {
        const apiUrl = document.getElementById('apiUrl').value;
        const apiKey = document.getElementById('apiKey').value;
        const autoClose = document.getElementById('autoClose').checked;

        chrome.storage.sync.set({
            apiUrl,
            apiKey,
            autoClose
        }, () => {
            const status = document.getElementById('status');
            status.style.display = 'block';
            setTimeout(() => {
                status.style.display = 'none';
            }, 2000);
        });
    });
});
