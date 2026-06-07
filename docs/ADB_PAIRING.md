# Connecting your phone (ADB pairing)

Panop talks to Chrome on your Android phone through the **Android Debug Bridge (adb)** and
Chrome's **DevTools protocol**. Panop bundles its own `adb`, so you never install the SDK.
This page explains how the connection works and how to fix it when a device won't appear.

## How it works

1. You enable **USB** or **Wireless debugging** on the phone (one-time).
2. Panop launches its sandboxed `adb` (downloaded to `panop_output/platform-tools/`).
3. `adb` forwards Chrome's debugging socket; Panop reads open tabs over `localhost:9222`.
4. Panop captures matching tabs and closes them via a DevTools command.

## USB (recommended for first use)

1. Connect the phone with a data-capable USB cable.
2. On the phone, accept **"Allow USB debugging?"** and tick **"Always allow from this
   computer"**. This stores a trusted RSA key — required before Wi-Fi will work.
3. Panop should show the device as connected within a few seconds.

## Wireless (Wi-Fi)

> Do the USB step above **once** first, so the computer's key is trusted.

1. Keep the phone and computer on the **same Wi-Fi network**.
2. On the phone: **Developer options → Wireless debugging → ON**.
3. Tap **Wireless debugging** to see the **IP address & port** (e.g. `192.168.1.42:37251`).
4. Enter that IP (and port if requested) into Panop's connection field and click **Connect**.

## Troubleshooting the connection

| Symptom | Cause | Fix |
|---|---|---|
| Device never appears | Debugging not enabled, or USB prompt dismissed | Re-enable USB debugging; unplug/replug and accept the prompt |
| "unauthorized" | Computer's RSA key not trusted yet | On the phone, **Developer options → Revoke USB debugging authorizations**, replug, accept the new prompt |
| Wi-Fi connect fails | Phone never paired over USB, or different network | Pair over USB once; confirm both devices share one Wi-Fi |
| Tabs read but won't close | Chrome not foregrounded / DevTools blocked | Open Chrome on the phone; ensure it's the default browsing app |
| Works then drops on Wi-Fi | Phone changed IP (DHCP) | Re-read the IP in Wireless debugging and reconnect; consider a DHCP reservation |

## Verifying manually (advanced)

If you want to confirm `adb` sees the phone independently of Panop:

```powershell
cd panop_output\platform-tools\platform-tools
.\adb.exe devices
```

A line ending in `device` (not `unauthorized` or `offline`) means the connection is healthy.
