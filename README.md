# Localization QA — Anh–Việt

Ứng dụng desktop Python/PySide6 cho macOS và Windows. Nhập CSV, kiểm tra kỹ thuật và đánh giá bản dịch bằng Gemini, duyệt bản sửa, lưu project SQLite `.lqa`, xuất CSV/Excel. Không huấn luyện model và không sửa APK.

## Chạy trên Mac

Cài Python 3.12 trở lên, mở Terminal trong thư mục project:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```

## Chạy trên Windows

Cài Python 3.12 trở lên. Trong PowerShell tại thư mục project:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run.py
```

## Sử dụng

1. Tạo project `.lqa`, nhập `samples/demo.csv` để thử. Có thể chọn chỉ kiểm tra kỹ thuật, không cần key hoặc Internet.
2. Lấy API key tại https://aistudio.google.com/apikey và nhập vào app. Nút lưu key dùng Keychain trên Mac / kho thông tin đăng nhập Windows qua keyring; không ghi key vào project.
3. Nhập tên model hỗ trợ structured output có trong tài khoản. Giá trị gợi ý `gemini-3.5-flash-lite` cần thay nếu không còn khả dụng. Xác minh model/hạn mức tại AI Studio và https://ai.google.dev/gemini-api/docs/pricing . App không thể đảm bảo free tier, không tự bật thanh toán, cũng không kiểm soát cấu hình billing của tài khoản.
4. Điền ngữ cảnh và thuật ngữ đã duyệt. Bấm kiểm tra. Nội dung Anh–Việt, ngữ cảnh dòng và ngữ cảnh project được gửi đến Google; dùng dữ liệu được phép gửi. Nội dung free tier có thể được dùng để cải thiện sản phẩm theo điều khoản Google.
5. Chọn một dòng, xem lý do, chỉnh bản dịch cuối và duyệt. Dòng đã duyệt được giữ nguyên và bỏ qua trong lần chạy tiếp. Không coi PASS là phê duyệt của con người.
6. Xuất CSV hoặc Excel. CSV thêm dấu nháy trước chuỗi có thể là công thức để mở an toàn trong Excel.

CSV bắt buộc có cột `key,english,vietnamese`, thêm cột `context` nếu có. Hỗ trợ CSV UTF-8, dấu phẩy, có hoặc không BOM. Key phải duy nhất. Khi nhập lại: thêm key mới, giữ key cũ không có trong file nhập, hủy đánh giá/phê duyệt của dòng có nội dung thay đổi.

Cache gắn với model, phiên bản prompt, ngữ cảnh và nội dung câu. Có khoảng nghỉ 5 giây giữa yêu cầu, thử lại tối đa 3 lần với lỗi dịch vụ tạm thời / 429; dừng sau đó để tránh gọi liên tục. Dừng có thể cần chờ yêu cầu hiện tại (timeout 30 giây mỗi lần gọi). Mỗi dòng hoàn tất được lưu. Nút tiếp tục dùng cache; không gửi lại các kết quả có cache.

## Đổi máy

Đóng app trước khi sao chép file `.lqa` sang máy khác. Không mở và đồng bộ cùng một project trên hai máy cùng lúc. Nhập API key riêng trên mỗi máy. File project chứa nội dung nội bộ, không chứa API key.

## GitHub và đóng gói

Tạo repo private và chỉ đưa code, requirements, tests, samples, workflow và README lên. `.gitignore` loại APK, dữ liệu đã trích, project và môi trường Python. Không lưu API key vào code hoặc GitHub.

Trong GitHub Actions, chạy **Build desktop apps** để tạo hai artifact. Giải nén và giữ nguyên toàn bộ thư mục bản Windows, chạy `LocalizationQA.exe`; Mac dùng `LocalizationQA.app`. macOS runner `macos-15` tạo bản Apple Silicon phù hợp máy M5; máy Mac Intel cần job riêng. Bản build chưa ký / notarize nên hệ điều hành có thể hiển thị cảnh báo nguồn phát hành. Chưa có bộ cài DMG/MSI.

Có thể build trên mỗi máy:

```sh
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --windowed --name LocalizationQA --collect-all keyring run.py
```

Kiểm tra:

```sh
python -m unittest discover -s tests -v
```

Giới hạn bản đầu: CSV đầu vào, chưa nhập XML/JSON trực tiếp; không đọc hình minh họa, không fine-tune; đánh giá AI cần người duyệt. Chưa kiểm thử Windows trên máy thật.

## Giao diện review mới

Tìm câu bằng key hoặc nội dung, lọc câu có lỗi / cần xem lại / đã duyệt. Khung bên phải hiển thị câu Anh, bản Việt, nhận xét và bản sửa cuối cùng. Nút duyệt kiểm tra placeholder trước khi lưu; nút tiếp theo chuyển đến câu chưa duyệt trong bộ lọc. Cấu hình Gemini có thể thu gọn để dành chỗ cho dữ liệu. Thanh tiến độ cập nhật sau từng câu và thông báo rõ lỗi dịch vụ thay vì báo hoàn tất khi gọi AI thất bại.

## Review và dữ liệu fine-tune

“Đã review” chỉ ghi nhận đã xem, không đồng nghĩa bản dịch đã đúng. Lưu ghi chú về câu chưa tốt, rồi nhập bản dịch cuối và bấm duyệt khi bạn chấp nhận. Chỉ dòng đã review có bản sửa đã duyệt và placeholder hợp lệ mới được xuất thành dữ liệu JSONL cho model local. Xuất dữ liệu không tự chạy fine-tune hoặc cập nhật Gemini.

Kết quả local/Gemini và nhận xét của agent là gợi ý; không được tự chuyển thành nhãn người duyệt. File project chứa tiến độ và ghi chú, chuyển riêng giữa hai máy khi app đã đóng. Thư mục outputs, dữ liệu JSONL, APK, model local và dữ liệu trích xuất được loại khỏi Git mặc định.

## Nhập dữ liệu JSON và Word

Nút **Nhập dữ liệu** nhận CSV, JSON và Word. File JSON có thể là danh sách các object `key`, `english`, `vietnamese`, `context` (tùy chọn), hoặc bọc danh sách trong `translations`. Xem `samples/demo.json` với dữ liệu giả lập. Dùng luồng **Nhập cặp JSON Anh–Việt** cho hai file nội dung ngôn ngữ tách riêng; chọn tiếng Anh trước và tiếng Việt sau, kiểm tra cảnh báo thiếu cặp trước khi nhập.

Với Word `.docx`, đặt nội dung trong bảng với tiêu đề `key | english | vietnamese | context` (context tùy chọn), hoặc viết các khối có nhãn `Key:`, `English:`, `Vietnamese:`, `Context:`. Không tự suy đoán cách ghép cặp từ tài liệu văn xuôi không có nhãn.

Word `.doc` đời cũ cần công cụ chuyển đổi có sẵn: `textutil` trên Mac hoặc LibreOffice trên máy hỗ trợ. Nếu không có, lưu tài liệu thành `.docx` trong Word rồi nhập lại. App không chỉnh file gốc; không chạy macro hay gửi tài liệu lên dịch vụ để chuyển đổi. Cả CSV/JSON/Word chỉ được nhập vào project sau khi đọc và kiểm tra cấu trúc; thao tác nhập chưa gửi nội dung đến Gemini.
