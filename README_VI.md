# Crawling Bot — Nền tảng OSINT Facebook

**Crawling Bot** là một nền tảng Social Media Intelligence (SOCMINT) toàn diện được thiết kế để phân tích hồ sơ Facebook, bài viết và mạng lưới người bình luận. Hệ thống kết hợp web scraping tự động, phân tích bằng AI, nhận diện khuôn mặt và trực quan hóa mạng lưới để tạo ra báo cáo tình báo chi tiết — tất cả chạy cục bộ với toàn quyền kiểm soát dữ liệu.

## Tính năng nổi bật

### Điều tra hồ sơ tự động
- Scraping toàn diện (about, ảnh, reels, bài viết văn bản)
- Phân tích bình luận bằng AI (cảm xúc, cảm tính, quan điểm)
- Phát hiện và gom cụm khuôn mặt sử dụng `face_recognition`
- Tự động chấm điểm và xếp hạng người bình luận
- Xác định quốc gia từ dữ liệu hồ sơ
- Đồ thị mạng lưới tương tác (star, co-comment, views tập trung)
- Tạo báo cáo PDF chuyên nghiệp

### Phân tích hàng loạt thủ công
- Điều tra đến 15 URL Facebook cụ thể (bài viết, ảnh, reel)
- Phân tích mạng lưới người bình luận
- Phát hiện mô hình cảm xúc
- Ánh xạ phân bố địa lý
- Chấm điểm và phân loại cấp độ hàng loạt

### Trí tuệ nhân tạo
- **Tích hợp LLM**: NVIDIA NIM (Llama 3.3 70B) cho phân tích đa ngôn ngữ
- **Phân tích cảm xúc**: Tích cực, tiêu cực, trung lập
- **Phát hiện cảm tính**: ủng hộ, tức giận, châm biếm, hung hăng
- **Phân loại quan điểm**: ủng hộ bài viết, phản đối bài viết, thảo luận trung lập
- **Nhận diện ngôn ngữ**: Tự động phát hiện 50+ ngôn ngữ

### Trí tuệ khuôn mặt
- Phát hiện khuôn mặt trong ảnh và ảnh chụp màn hình bài viết
- Gom cụm danh tính (cùng một người qua nhiều bài viết)
- Trích xuất và lưu ảnh cắt khuôn mặt
- Phân tích tần suất xuất hiện
- Tích hợp với đồ thị mạng lưới

### Phân tích mạng lưới
- **Mạng Star**: Hồ sơ mục tiêu kết nối với tất cả người bình luận
- **Mạng Co-Comment**: Tiết lộ hành vi phối hợp/đồng bộ
- **Top 7 Tập trung**: Mối quan hệ gần gũi nhất (tương tác cao)
- **Bottom 7 Tập trung**: Các tiếng nói chỉ trích hoặc tương tác thấp
- Trực quan hóa HTML tương tác với `pyvis`
- Biểu tượng cờ quốc gia và mã màu theo cấp độ

### Hệ thống chấm điểm cấp độ

Người bình luận được tự động phân loại thành 5 cấp dựa trên mẫu tương tác:

- **Strong Supporter** (điểm > +0.5): Rất tích cực, tương tác mạnh
- **Supporter** (+0.1 đến +0.5): Nói chung tích cực
- **Neutral** (-0.1 đến +0.1): Cân bằng hoặc tương tác tối thiểu
- **Low Interaction** (-0.5 đến -0.1): Tương tác hạn chế
- **Critical Voice** (< -0.5): Quan điểm phản đối, cường độ cao

### Báo cáo PDF chuyên nghiệp

Báo cáo nhiều trang A4 được tạo bằng `reportlab`:
- Trang bìa với thông báo bảo mật
- Tóm tắt điều hành với số liệu chính
- Top 7 người ủng hộ và phản đối (với dữ liệu mở rộng)
- Biểu đồ thông minh bình luận (cảm xúc, cảm tính, quan điểm)
- Trực quan hóa phân bố quốc gia
- Đồ thị mạng lưới nhúng
- Thư viện cụm khuôn mặt

## Kiến trúc

```
┌─────────────────────────────────────────────────────────────┐
│                     Giao diện Flask Web                     │
│              (Dashboard, Báo cáo, Công cụ)                  │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                Pipeline Orchestrator (app.py)               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │ Scrapers │ │   AI     │ │ Scoring  │ │ Network  │        │
│  │ (fb_*)   │ │Analysis  │ │ & Country│ │  Graphs  │        │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Cơ sở dữ liệu SQLite                     │
│  ┌─────────────────┐              ┌─────────────────────┐   │
│  │  socmint.db     │              │  socmint_manual.db  │   │
│  │ (Hồ sơ tự động) │              │  (Phân tích batch)  │   │
│  └─────────────────┘              └─────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              NVIDIA NIM API (Llama 3.3 70B)                 │
│          Giới hạn tốc độ: 40 yêu cầu/phút                   │
└─────────────────────────────────────────────────────────────┘
```

### Luồng dữ liệu: Điều tra hồ sơ tự động

1. **Xác thực Cookie**: Kiểm tra phiên Facebook qua `fb_cookies.json`
2. **Thu thập dữ liệu** (Tuần tự):
   - `fb_about.py` → Metadata hồ sơ
   - `fb_reels.py` → Bài viết Reel
   - `fb_photos.py` → Bài viết ảnh với bình luận
   - `fb_posts.py` → Bài viết văn bản với bình luận
3. **Nhập DB**: `socmint_db_import.py` chuyển JSON thô thành SQLite
4. **Phân tích AI**:
   - `image_intelligence.py` → Cảnh, đối tượng, biểu tượng chính trị/tôn giáo
   - `text_post_intelligence.py` → Chủ đề, cấu trúc narrative, chỉ số đe dọa
   - `comment_intelligence_offline.py` → Cảm xúc, cảm tính, quan điểm (batch)
5. **Xây dựng tình báo**:
   - `face_intelligence.py` → Phát hiện, gom cụm khuôn mặt
   - `commentor_scoring.py` → Gán cấp độ, làm giàu top 7
   - `commentor_country.py` → Địa lý từ hồ sơ
   - `network_graph.py` → Đồ thị HTML tương tác
6. **Tạo báo cáo**: `threat_report.py` → PDF chuyên nghiệp

### Luồng dữ liệu: Phân tích hàng loạt

1. **Thu thập URL**: Người dùng cung cấp đến 15 URL Facebook
2. **Scraping thống nhất**: `fb_manual_unified.py` thu thập tất cả bài viết
3. **Nhập DB**: `socmint_manual_db.py` vào `socmint_manual.db`
4. **Phân tích AI** (giống trên, nhưng theo batch)
5. **Chấm điểm Batch**: `commentor_scoring.run_batch_scoring()`
6. **Mạng lưới Batch**: `network_graph.run_for_batch()`
7. **Tạo báo cáo**: PDF cụ thể cho batch

## Bắt đầu nhanh

### Yêu cầu

- **Python 3.10+** với `pip`
- **Cookies Facebook** (xem [Thiết lập phiên](#thiết-lập-phiên))
- **Docker** (tùy chọn, khuyên dùng cho production)

### Cài đặt

1. **Clone và setup**:
```bash
cd /home/death/Documents/ThucTap
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Cài đặt dependencies hệ thống** (cho face recognition):
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y cmake build-essential libopenblas-dev

# Để tối ưu, cũng cài:
sudo apt install -y libjpeg-dev zlib1g-dev
```

3. **Cấu hình LLM API**:
   - Mặc định: NVIDIA NIM (cần API key)
   - Sửa `app/llm_client.py` hoặc set biến môi trường:
```bash
export LLM_API_KEY="your-nvidia-api-key"
export LLM_BASE_URL="https://integrate.api.nvidia.com/v1"
export LLM_MODEL="meta/llama-3.3-70b-instruct"
```

4. **Nhập cookies Facebook** (xem [Thiết lập phiên](#thiết-lập-phiên))

### Chạy với Docker (Khuyến nghị)

```bash
# Build và start
docker-compose up -d

# Xem logs
docker-compose logs -f

# Dừng
docker-compose down
```

Truy cập giao diện web tại: `http://localhost:5000`

### Chạy cục bộ (Development)

```bash
cd app
python app.py
```

Truy cập tại: `http://localhost:5000`

## Thiết lập phiên Facebook

Crawling Bot yêu cầu phiên Facebook hợp lệ lưu trong `app/fb_cookies.json`.

### Phương pháp 1: Cookie-Editor Extension (Khuyến nghị)

1. Cài extension **Cookie-Editor** vào trình duyệt
2. Đăng nhập Facebook bình thường
3. Mở Cookie-Editor khi đang ở `facebook.com`
4. Click **Export** → **Export as JSON**
5. Copy JSON
6. Trong Crawling Bot: **Công cụ → Nhập Cookie Phiên**
7. Dán và click **Nhập Cookies**

Hoạt động trên: Windows, macOS, Linux — không cần Selenium.

### Phương pháp 2: Làm mới Selenium (Chỉ Linux)

1. Trong Crawling Bot: **Công cụ → Làm mới Cookie Phiên**
2. Click **Bắt đầu làm mới Cookie**
3. Cửa sổ trình duyệt mở — đăng nhập Facebook trong 60 giây
4. Cookies tự động lưu vào `fb_cookies.json`

**Quan trọng**: Phiên Facebook hết hạn. Làm mới cookies mỗi 2 ngày.

## Hướng dẫn sử dụng

### Điều tra hồ sơ tự động

1. Vào **Trang chủ** → **Bắt đầu điều tra**
2. Nhập URL hồ sơ (vd: `https://www.facebook.com/username`)
3. Chọn loại quét:
   - **Nhẹ**: 5 bài mỗi loại (nhanh, ~10-15 phút)
   - **Trung bình**: 10 bài mỗi loại (khuyên dùng, ~20-30 phút)
   - **Sâu**: 20 bài mỗi loại (toàn diện, ~40-60 phút)
4. Tùy chọn: Bật "Bổ sung dữ liệu hồ sơ top 7" để scrap đầy đủ
5. Click **Bắt đầu điều tra**
6. Theo dõi tiến độ real-time trên dashboard

### Phân tích hàng loạt

1. Vào **Trang chủ** → **Phân tích hàng loạt**
2. Nhập nhãn batch (tùy chọn, tự động nếu để trống)
3. Dán đến 15 URL Facebook (bài viết, ảnh, reel)
4. Chọn độ sâu quét
5. Click **Bắt đầu phân tích hàng loạt**
6. Xem dashboard cụ thể cho batch

### Tính năng Dashboard

- **Trạng thái Real-time**: Xem giai đoạn pipeline hiện tại (thu thập, phân tích, xây dựng, báo cáo)
- **Thống kê**: Bài viết, bình luận, người bình luận, khuôn mặt phát hiện
- **Top 7 Mạng lưới**: Người ủng hộ cao điểm với hồ sơ đã làm giàu
- **Thông minh Bình luận**: Phân tích cảm xúc/cảm tính/quan điểm
- **Phân bố Quốc gia**: Bản đồ địa lý người bình luận
- **Cụm Khuôn mặt**: Thư viện người duy nhất được phát hiện
- **Đồ thị Mạng lưới**: Trực quan hóa HTML tương tác
- **Báo cáo PDF**: Tải báo cáo tình báo hoàn chỉnh

## Cấu trúc dự án

```
ThucTap/
├── app/
│   ├── app.py                    # Flask app + pipeline orchestration
│   ├── templates/                # Jinja2 HTML templates
│   ├── static/
│   │   └── js/
│   │       └── dashboard.js      # Frontend interactivity
│   ├── icons/                    # Logo, threat/user icons
│   ├── reports/                  # Generated PDF reports + graphs
│   ├── face_data/                # Face crops (organized by profile)
│   ├── post_screenshots/         # Text post screenshots
│   ├── status/                   # JSON status files per investigation
│   │
│   ├── fb_about.py               # Profile about scraper
│   ├── fb_photos.py              # Photo posts scraper
│   ├── fb_reels.py               # Reel posts scraper
│   ├── fb_posts.py               # Text posts scraper
│   ├── fb_manual_unified.py      # Unified manual batch scraper
│   │
│   ├── pw_utils.py               # GraphQL/DOM extraction utilities
│   ├── scrapling_session.py      # Stealth Playwright session manager
│   │
│   ├── socmint_db_import.py      # Import JSON → socmint.db
│   ├── socmint_manual_db.py      # Import batch JSON → socmint_manual.db
│   │
│   ├── image_intelligence.py     # AI image analysis (scene, objects, symbols)
│   ├── text_post_intelligence.py # AI text analysis (topics, narratives)
│   ├── comment_intelligence_offline.py  # AI comment analysis
│   │
│   ├── commentor_scoring.py      # Scoring engine, tier assignment, enrichment
│   ├── commentor_country.py      # Country detection from profiles
│   ├── face_intelligence.py      # Face detection & clustering
│   ├── network_graph.py          # Pyvis graph generation
│   ├── threat_report.py          # PDF report generation (ReportLab)
│   │
│   ├── llm_client.py             # NVIDIA NIM API client + rate limiting
│   ├── translations.py           # i18n (English/Vietnamese)
│   ├── db_cleaner.py             # Database cleanup utility
│   ├── refresh_cookies.py        # Selenium cookie refresh (Linux)
│   └── sign-in.py                # Legacy auth helper
│
├── docker-compose.yml            # Docker production deployment
├── Dockerfile                    # Container image definition
├── requirements.txt              # Python dependencies
├── README.md                     # This file
└── .gitignore
```

## Cấu hình

### Biến môi trường

```bash
# LLM Configuration (NVIDIA NIM)
export LLM_API_KEY="nvapi-..."
export LLM_BASE_URL="https://integrate.api.nvidia.com/v1"
export LLM_MODEL="meta/llama-3.3-70b-instruct"
export LLM_VISION_MODEL="meta/llama-3.2-11b-vision-instruct"

# Flask
export FLASK_ENV="production"
export FLASK_HOST="0.0.0.0"
export FLASK_PORT="5000"
export SECRET_KEY="random-32-char-string"

# Optional: Custom database paths
export SOCMINT_DB="/path/to/socmint.db"
export SOCMINT_MANUAL_DB="/path/to/socmint_manual.db"
```

### Giới hạn Scan

Sửa `SCAN_LIMITS` trong `app/app.py`:

```python
SCAN_LIMITS = {
    'light':  {'photos': 5,  'reels': 5,  'posts': 5},
    'medium': {'photos': 10, 'reels': 10, 'posts': 10},
    'deep':   {'photos': 20, 'reels': 20, 'posts': 20},
}
```

### Ngưỡng Gom cụm Khuôn mặt

Sửa `TOLERANCE` trong `app/face_intelligence.py`:

```python
TOLERANCE = 0.42  # Phạm vi: 0.4 (nghiêm ngặt) đến 0.6 (lỏng lẻo)
```

## Dependencies

### Gói Python Core

- **Flask** — Web framework
- **Playwright** — Tự động hóa trình duyệt (stealth scraping)
- **face_recognition** — Phát hiện & gom cụm khuôn mặt (dlib backend)
- **opencv-python** — Xử lý ảnh
- **numpy** — Phép toán số học
- **reportlab** — Tạo PDF
- **matplotlib** + **seaborn** — Biểu đồ
- **pyvis** + **networkx** — Đồ thị mạng lưới
- **requests** + **urllib3** — HTTP client

### AI/LLM

- **NVIDIA NIM** — Cloud LLM API (Llama 3.3 70B)
- Rate limiter tích hợp (40 req/min)

### Tùy chọn (cho cookie refresh)

- **selenium** + **webdriver-manager** (chỉ Linux)

Xem `requirements.txt` để danh sách đầy đủ với versions.

## Bảo mật & Quyền riêng tư

- **100% Cục bộ**: Tất cả dữ liệu ở máy bạn (trừ LLM API calls)
- **Không Cloud Storage**: Ảnh khuôn mặt, hồ sơ, báo cáo chỉ cục bộ
- **Chỉ Phiên**: Cookies Facebook lưu cục bộ, không chia sẻ
- **Rate Limited**: Tôn trọng giới hạn Facebook và LLM API
- **Xem xét GDPR**: Sử dụng có trách nhiệm, chỉ cho mục đích OSINT hợp pháp

## Xử lý sự cố

### "Session expired" hoặc "Check cookies"
- Dùng **Công cụ → Làm mới Cookie Phiên** hoặc nhập lại qua Cookie-Editor
- Phiên Facebook hết hạn ~mỗi 48 giờ

### Phát hiện khuôn mặt thất bại
```bash
# Cài dependencies dlib hệ thống
sudo apt install -y cmake build-essential libopenblas-dev
pip install dlib face_recognition --no-cache-dir
```

### Lỗi LLM API
- Kiểm tra `LLM_API_KEY` đã set và hợp lệ
- Kiểm tra rate limit: 40 requests/phút
- Test kết nối: `python -c "import llm_client; print(llm_client.check_llm())"`

### Docker container thoát ngay
```bash
docker-compose logs  # Kiểm tra error output
docker-compose up    # Chạy foreground để xem logs
```

### Đồ thị không hiện icons
- Đảm bảo thư mục `icons/` tồn tại với `threat.png` và `user.png`
- Hoặc fallback internet sẽ load từ CDN

### Database bị khóa
- Chỉ một Flask process nên truy cập DB cùng lúc
- Nếu dùng Docker, đảm bảo container chạy: `docker-compose ps`

## Hiệu năng

### Thời gian điều tra điển hình (Medium scan)

| Giai đoạn | Thời gian |
|-----------|-----------|
| About scrape | 30-60s |
| Photos scrape (10) | 2-4 phút |
| Reels scrape (10) | 2-4 phút |
| Posts scrape (10) | 2-4 phút |
| AI image analysis | 1-2 phút |
| AI text analysis | 1-2 phút |
| AI comment analysis | 3-5 phút (LLM rate-limited) |
| Phát hiện khuôn mặt | 2-3 phút |
| Scoring + country | 1-2 phút |
| Network graphs | 30-60s |
| Báo cáo PDF | 30-60s |
| **Tổng** | **15-25 phút** (tùy thuộc vào tốc độ của LLM) |

### Yêu cầu tài nguyên

- **RAM**: Tối thiểu 4GB, Khuyến nghị 8GB+
- **Lưu trữ**: ~100MB mỗi điều tra (bao gồm face crops)
- **CPU**: Multi-core khuyến nghị cho face clustering
- **GPU**: Tùy chọn (face_recognition CPU-only)

### Điểm cần cải thiện

- Kết hợp với phương án crawl mà Đăng đã xây dựng, sử dụng bắt GraphQL như 1 fallback
- Thiết lập thêm cơ chế xoay vòng hoặc đa cookies để hạn chế tình trạng bị bắt bot do chạy chế độ batch, và số lượng user_agent cũng nên tăng theo số lượng cookies - file `scarpling_session.py`
- Thêm cơ chế đăng nhập thủ công để tự động export cookies và import cookies, cookies cần refresh mỗi 48h
- Chỉnh sửa lại các prompt cho hợp với nghiệp vụ - `comment_intelligence_offline.py`, `commentor_country.py`, `image_intelligence.py`, `text_post_intelligence.py`
- Chỉnh sửa lại giao diện và phong cách báo cáo -> nên trình bày theo sơ đồ cây (gia phả) để dễ nắm bắt
