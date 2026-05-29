# LocalShare 📡

### Instant wireless file transfer between devices on the same Wi-Fi

![Python](https://img.shields.io/badge/Python-3.7%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

Transfer files instantly between devices directly over Wi-Fi — no cables, cloud uploads, accounts, or extra apps required.

Built with pure Python and a sleek responsive web interface that works on desktop and mobile browsers.

---

## ✨ Features

* ⚡ Instant local file transfer over Wi-Fi
* 📱 Works directly in Safari, Chrome, Edge, and Firefox
* 🖥️ Responsive desktop & mobile interface
* 📂 Multi-file upload support
* 🖱️ Drag & drop uploads
* 📊 Real-time upload progress
* 📷 Built-in QR code for instant mobile access
* ⬇️ One-click file downloads
* 🗑️ Delete files directly from the browser
* 🔄 Auto-refreshing file list
* 💤 Auto-shutdown when browser tab closes
* 🌐 Works across Windows, macOS, Linux, iPhone, and Android
* 🐍 Single Python file
* 🔒 Fully local — no internet required after startup

---

# 📸 Preview & Screenshots

## Console Interface

```text
╔══════════════════════════════════════╗
           LocalShare  🚀
╠══════════════════════════════════════╣
║ Local  →  http://localhost:8889      ║
║ Mobile →  http://192.168.1.42:8889   ║
╠══════════════════════════════════════╣
║ Scan the QR code or open the URL     ║
║ on your phone (same Wi-Fi required)  ║
╚══════════════════════════════════════╝
```

## Web UI

![Desktop UI](assets/desktop.png)

---

# 🚀 Quick Start

## 1 · Requirements

* Python 3.7+
* `psutil`

Install dependency:

```bash
pip install psutil
```

Make sure your devices are connected to the same Wi-Fi network.

---

## 2 · Clone the Repository

```bash
git clone https://github.com/parhamhmtt/localshare.git
cd localshare
```

---

## 3 · Run the Server

```bash
python server.py
```

If `python` doesn't work:

```bash
python3 server.py
```

The browser opens automatically.

---

# 📱 Using LocalShare

## Connect from Your Phone

After starting the server:

* Scan the QR code shown in the browser
  OR
* Open the displayed Mobile URL manually

Example:

```text
http://192.168.1.42:8889
```

---

## Upload Files

1. Open LocalShare on your phone
2. Tap “Choose Files”
3. Select photos, videos, or documents
4. Tap “Upload Files”

You can also drag & drop files from desktop browsers.

Uploaded files are saved in:

```text
/uploads
```

---

## Download Files

All uploaded files appear instantly in the web interface.

Tap the ⬇ download button beside any file.

---

# 🌐 Browser Support

Tested on:

* Safari (iPhone/iPad)
* Chrome
* Edge
* Firefox

---

# 🔐 Privacy & Security

* No cloud services
* No analytics
* No tracking
* No external servers
* Files never leave your local Wi-Fi network

Note:

LocalShare is intended for trusted/private networks.
Anyone connected to the same network can access the transfer page while the server is running.

---

# 📂 Project Structure

```text
LocalShare/
│
├── assets/
│   └── desktop.png
├── server.py
├── README.md
└── LICENSE
```

---

# ⚙️ Configuration

You can customize the port and upload location near the top of `server.py`.

```python
PORT = 8889

UPLOAD_DIR = Path(__file__).parent / "uploads"
```

---

# 🔥 Can't Reach the Page?

Windows Firewall may block incoming connections.

Run PowerShell as Administrator:

```powershell
netsh advfirewall firewall add rule name="LocalShare" dir=in action=allow protocol=TCP localport=8889
```

Remove the rule later:

```powershell
netsh advfirewall firewall delete rule name="LocalShare"
```

---

# 🛠 Troubleshooting

| Problem                      | Solution                                    |
| ---------------------------- | ------------------------------------------- |
| Phone can't connect          | Make sure both devices use the same Wi-Fi   |
| QR code doesn't open page    | Try opening the Mobile URL manually         |
| URL shows `127.0.0.1`        | Disable VPN and restart the server          |
| `python server.py` not found | Use `python3 server.py`                     |
| Upload failed                | Check firewall settings                     |
| Port already in use          | LocalShare automatically finds another port |

---

# 🧠 How It Works

LocalShare starts a lightweight HTTP server on your computer and exposes a private web interface over your local network.

Any device connected to the same Wi-Fi can open the generated URL in a browser and instantly upload or download files.

No internet connection is required after startup.

All transfers remain entirely inside your local network.

---

# 🛑 Stop the Server

Press:

```text
CTRL + C
```

inside the terminal.

or close the localhost browser tab to auto-stop the server.

---

# ⭐ Why LocalShare?

Most file-sharing solutions require:

* installing apps
* creating accounts
* cloud uploads
* USB cables

LocalShare avoids all of that.

Run one Python file, open the QR code, and start transferring instantly.

---

# 📜 License

MIT License

Feel free to use, modify, and share.

---

# ❤️ Contributing

Pull requests, improvements, and feature ideas are welcome.

If you like the project, consider giving it a ⭐ on GitHub.
