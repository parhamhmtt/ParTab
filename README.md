# LocalShare 📡  
### Instant Wireless File Transfer Between mobile devices & Windows

Transfer files between your mobile device and Windows PC directly over Wi-Fi — no cables, no cloud uploads, no third-party apps.

Built with pure Python and a sleek responsive web interface that works on desktop and mobile browsers.

---

## ✨ Features

- ⚡ **Instant local transfer** over your home Wi-Fi
- 📱 **Works directly in Safari / browser**
- 📂 **Multi-file upload support**
- 📊 **Real-time upload progress**
- 🖥️ **Beautiful responsive UI**
- ⬇️ **One-click file downloads**
- 🗑️ **Delete files from the browser**
- 🔄 **Auto-refreshing file list**
- 🧩 **Zero external dependencies**
- 🐍 **Single Python file**

---

# 📸 Preview

Open the generated local URL on your phone and start transferring instantly.

```text
╔══════════════════════════════════════╗
           LocalShare  🚀
╠══════════════════════════════════════╣
║ Local  →  http://localhost:8889      ║
║ Mobile →  http://192.168.1.42:8889   ║
╠══════════════════════════════════════╣
║ Open the Mobile URL on your iPhone   ║
║ (same Wi-Fi required)                ║
╚══════════════════════════════════════╝
```

---

# 🚀 Quick Start

## 1 · Requirements

- Python **3.7+**
- mobile and PC connected to the **same Wi-Fi network**

Download Python from:  
https://www.python.org

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

## Upload Files 

1. Open the **URL** shown in your web browser
2. Tap **“Choose Files”**
3. Select photos, videos, or documents
4. Tap **Upload Files**

Uploaded files appear in:

```text
/uploads
```

---

## Download Files 

All uploaded files are listed in the web interface.

Simply tap the ⬇ download button beside any file.

---

# 📂 Project Structure

```text
LocalShare/
│
├── server.py          # Main server application
├── uploads/           # Uploaded files are stored here
└── README.md
```

---

# ⚙️ Configuration

You can customize the port and upload location at the top of `server.py`.

```python
PORT = 8889

UPLOAD_DIR = Path(__file__).parent / "uploads"
```

---

# 🔥 Cant reach the page ? →  Windows Firewall Fix

If your phone cannot connect, Windows Firewall may be blocking the server.

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

| Problem | Solution |
|---|---|
| Phone can't connect | Make sure both devices are on the same Wi-Fi |
| URL shows `127.0.0.1` | Disable VPN and restart the server |
| `python server.py` not found | Use `python3 server.py` |
| Upload failed | Check firewall settings |
| Port already in use | The app automatically finds another free port |

---

# 🧠 How It Works

LocalShare runs a lightweight HTTP server on your computer and exposes a clean web interface accessible from any device on the same local network.

No internet connection is required after startup.

All transfers remain entirely inside your local network.

---

# 🔒 Privacy

- No cloud services
- No analytics
- No tracking
- No external servers
- Files never leave your Wi-Fi network

---

# 🧩 Built With

- Python standard library
- HTML/CSS/JavaScript
- `http.server`
- `socketserver`

No frameworks. No dependencies.

---

# 🛑 Stop the Server

Press:

```text
CTRL + C 
```

in the terminal.

---

# ⭐ Why LocalShare?

Most file-sharing solutions require:

- installing apps
- creating accounts
- uploading to the cloud
- using cables

LocalShare avoids all of that.

Just run one Python file and transfer instantly.

---

# 📜 License

MIT License

Feel free to use, modify, and share.

---

# ❤️ Contributing

Pull requests, improvements, and feature ideas are welcome.

If you like the project, consider giving it a ⭐ on GitHub.
