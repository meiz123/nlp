# Nhập bảng so sánh đã lưu

`localqa.comparison` nhập bảng local–Gemini vào project `.lqa` hoàn toàn trên máy. Không gọi model, không gửi dữ liệu, không huấn luyện.

```python
from localqa.core import Project
from localqa.comparison import import_comparison

project = Project('review.lqa')
count = import_comparison(project, 'comparison_results.csv')
project.close()
```

CSV UTF-8 cần các cột `key`, `english`, `original_vietnamese`, `local_translation`, `gemini_translation`, `winner`, `reason`. `winner` nhận `local`, `gemini`, `tie`, `unresolved`. Các cột ngữ cảnh và nhận xét backend là tùy chọn. Đọc và kiểm tra toàn bộ CSV trước khi cập nhật project; key trùng, dòng thiếu ô hoặc kết luận không hợp lệ sẽ được báo lỗi.

Câu Anh và bản Việt gốc được lưu làm đầu vào, không bị thay bằng đề xuất của model. Kết quả lưu riêng theo backend `local`, `gemini`, `comparison`, có nguồn `imported_comparison_csv`. Cột `translation` của từng backend là bản model đề xuất hoặc bản gốc được model giữ lại. CSV không chứa đủ thông tin để suy ra tên model, phiên bản hoặc prompt; importer không tự bịa các thông tin đó.

Mặc định, kết luận của agent và cột `human_approved` **không** đánh dấu câu là đã review hoặc được phê duyệt. Nhập lại cùng câu giữ ngữ cảnh và feedback đã lưu. Khi đầu vào thay đổi, project xóa trạng thái review/phê duyệt và ghi chú cũ để tránh dùng nhãn đã lỗi thời.

Nếu người dùng chủ động yêu cầu khôi phục một CSV feedback đã tự chỉnh, gọi `import_comparison(..., import_feedback=True)`. Lúc đó cần cột `reviewed` rõ ràng; `review_notes` và `approved_translation` được đọc. Bản sửa không trống chỉ được nhập khi `reviewed=TRUE` và placeholder khớp. Không dùng tùy chọn này cho file kết quả model chưa được người dùng duyệt.

Để giao diện đọc hai bản dịch và kết luận:

```python
results = project.backend_results(key)
local_text = results.get('local', {}).get('translation', '')
gemini_text = results.get('gemini', {}).get('translation', '')
verdict = results.get('comparison', {}).get('winner', '')
```

Bản gốc APK và kết quả thực tế nằm ngoài mã nguồn công khai. Kiểm thử dùng dữ liệu giả lập.
