# Squid Log Parser Dashboard 🐙📊

A modern tool for parsing and analyzing Squid logs, providing a sleek and user-friendly dashboard to visualize real-time connection data. This project helps network administrators monitor and manage Squid proxy connections effectively.

---

![DEMO](https://github.com/kaelthasmanu/SquidStats/blob/main/assets/photo_2025-03-16_10-33-06.jpg "DEMO")

![DEMO](https://github.com/kaelthasmanu/SquidStats/blob/main/assets/photo_2025-04-04_15-45-33.jpg "DEMO")

![DEMO2](https://github.com/kaelthasmanu/SquidStats/blob/main/assets/Screenshot%20from%202025-03-18%2001-02-36.png "DEMO2")

## 🌟 Features
- **Real-time Log Parsing**: Parses active Squid connections and displays detailed information.
- **User Monitoring**: Identifies connections by username, URI, and log type.
- **Metrics Overview**:
  - Total read and written data for each connection.
  - Number of requests per connection.
  - Delay pool usage.
- **Interactive Dashboard**: Clean interface for easy data interpretation.
- **Squid Cache Statistics**: 
  - Stored entries.
  - Used and free capacity
  - Maximum and current cache size
  - Disk space and inode usage
  - Age of cached objects
- **Logs Users**: 
  - User activity monitoring 👥
  - Beautiful visualizations 📊 
  - Advanced filtering & search 🔍 
  - Paginated results 📄

---

### ⚠️ First Execution Alert ⚠️
Warning: 🚨 The first execution may cause high CPU usage.

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Squid proxy server
- `squidclient` installed on the server
- For compatibility with user logs, use this format in /etc/squid/squid.conf:
```bash 
  logformat detailed \
  "%ts.%03tu %>a %ui %un [%tl] \"%rm %ru HTTP/%rv\" %>Hs %<st %rm %ru %>a %mt %<a %<rm %Ss/%Sh %<st/%<bs"
  
  access_log /var/log/squid/access.log detailed
```
### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/kaelthasmanu/SquidStats.git
   cd SquidStats
   ```
2. Install requeriments python with pip or pip3:
  ```bash
    pip install -r requirements.txt
  ```
3. Create a .env file in the project root and add the following content:
  ```bash
    SQUID_HOST="127.0.0.1"
    SQUID_PORT=3128
    FLASK_DEBUG = "True"
    SQUID_LOG = "/home/manuel/Desktop/SquidStats/parsers/access.log"
    DATABASE = "/home/manuel/Desktop/SquidStats/logs.db"
    REFRESH_INTERVAL = 60
  ```
4. Run App with python or python3  🚀:
  ```bash
    python app.py
  ```
4. With your preferred browser, visit the installation URL:
  ```bash
    http://ip/hostname:5000 
  ```

🕒 Run on System Startup
To ensure the application starts automatically when the system boots, add the following cron job:
1. Open with a editor the file crontab
```bash
nano /etc/crontab
```
2. Add the following line to the crontab file(change path_app for your path):
```bash
@reboot root nohup python3 path_app/app.py &
```
3. Save

## 🧪 Testing Information
This software has been thoroughly tested and is compatible with Squid version 6.12. Please ensure your Squid installation matches this version or newer for optimal performance.

## 🛠️ Technologies Used

  Backend: Python, Flask
  Frontend: HTML, CSS

## 🤝 Contributing
1. Fork the repository:
   ```bash
   git checkout -b feature-name
   ```
2.Create a new branch for your feature or fix:
 ```bash
 git checkout -b feature-name
 ```
3.Commit your changes and push the branch:
  ```bash
  git push origin feature-name
  ```
4.Open a pull request.

<!-- CONTACT -->
## Contact
Manuel - ([Telegram](https://t.me/king_0f_deathhh)) ([Email](mailto:manuelalberto.gorrin@gmail.com))

Project Link: ([SquidStats](https://github.com/kaelthasmanu/cucuota))

## 📄 License

This project is licensed under the MIT License. See the LICENSE file for details.
