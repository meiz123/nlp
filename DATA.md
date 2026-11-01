# Chuẩn bị dữ liệu cho Localization QA

Module `localqa.data` chạy hoàn toàn trên máy: không đọc API key, không gọi Gemini, không chỉnh sửa APK hoặc file nguồn. Cùng một lệnh dùng được trên Mac/Windows khi chạy trong môi trường Python của project. Trên Windows thay `python3` bằng `python` nếu cần.

## Đầu vào CSV

Cột bắt buộc: `key`, `english`, `vietnamese`. Cột tùy chọn: `context`. Mỗi key phải duy nhất và không được trống. CSV sử dụng dấu phẩy, UTF-8 có hoặc không BOM; chuỗi chứa dấu phẩy hoặc xuống dòng phải được đặt trong dấu nháy theo chuẩn CSV.

Không tự cắt khoảng trắng hay sửa câu dịch: khoảng trắng và placeholder cần được giữ nguyên để công cụ QA phát hiện. Trình đọc báo lỗi nếu trùng tên cột, trùng key hoặc số ô trong dòng không khớp tiêu đề. Các cột khác ngoài bốn cột chuẩn không được đưa vào đầu ra lấy mẫu.

## Ghép JSON Anh–Việt

```sh
python3 -m localqa.data pair-json apk-localization/data_home_en.json apk-localization/data_home_vi.json --output apk-localization/paired_content_v2.csv --strict
```

Đầu ra gồm CSV chuẩn để nhập vào ứng dụng và `paired_content_v2.report.json` chứa số lượng, cảnh báo và SHA-256 của hai file nguồn. Có thể đổi nơi lưu báo cáo bằng `--report PATH`.

Quy tắc ghép:

- Chỉ lấy giá trị chuỗi ở các trường hiển thị `title`, `name`, `categoryLabel`, `description`; bỏ ID, đường dẫn ảnh/video, URL và metadata.
- Trong mảng, đối tượng có `id` được ghép theo ID, kể cả khi thứ tự hai ngôn ngữ khác nhau. Ví dụ: `/tutorials/@id=tutorial-1/name`.
- Đối tượng không có ID (như bước hướng dẫn) được ghép theo vị trí, bắt đầu từ 0: `/tutorials/@id=tutorial-1/data/0/description`. Thêm cảnh báo về giả định thứ tự trong cột `context`.
- Ký tự `/` và `~` trong ID được mã hóa thành `~1` và `~0` để tránh nhầm đường dẫn.
- Nếu một ID bị lặp trong cùng mảng, không ghép các đối tượng có ID đó. Báo `duplicate_id`; giữ lại phía ngôn ngữ còn lại nếu có để hiển thị thiếu cặp, thay vì âm thầm lấy bản cuối.
- Nếu thiếu một phía, vẫn xuất dòng với ô trống và báo `missing_english` hoặc `missing_vietnamese`. Chuỗi chỉ có khoảng trắng được báo `blank_*`. Trường hiển thị không phải chuỗi được báo `invalid_text_type`.

`--strict` vẫn xuất CSV và báo cáo, nhưng trả mã thoát 2 khi có cảnh báo dữ liệu. Mã 0 nghĩa là không có các cảnh báo cấu trúc trên; **không có nghĩa bản dịch đã đúng hoặc tự nhiên**.

Giới hạn: chưa có ID cho từng bước thì không thể xác định chắc chắn hai ngôn ngữ có đảo thứ tự bước hay không. Khi dev bổ sung ID bước, module sẽ tự dùng ID. Chuỗi giống nhau giữa Anh và Việt không tự động bị đánh dấu lỗi vì có tên riêng và thuật ngữ được giữ nguyên.

## Lấy mẫu tái lập

```sh
python3 -m localqa.data sample apk-localization/paired_content_v2.csv --output apk-localization/sample_20.csv --count 20 --seed 29
```

Mẫu được chọn sau khi sắp xếp theo key, nên cùng dữ liệu, `seed`, số lượng và phiên bản Python sẽ cho cùng các key dù thứ tự dòng CSV thay đổi. Báo cáo đi kèm ghi SHA-256 nguồn, seed, số câu và các key đã chọn. Yêu cầu số câu từ 1 đến tổng số dòng. Không ghi đè nguồn.

Lấy mẫu ngẫu nhiên giúp thử luồng ứng dụng; không bảo đảm đủ đại diện cho mọi loại lỗi. Khi có dữ liệu chuẩn, nên thêm bộ đánh giá riêng gồm câu đúng, sai nghĩa, không tự nhiên, thuật ngữ và placeholder, kèm người duyệt xác nhận.

## Kết quả kiểm tra dữ liệu APK tham chiếu ban đầu

Hai file `data_home_en.json` và `data_home_vi.json` có 66 tutorial mỗi file. Module ghép được **1.426 trường hiển thị Anh–Việt**, không gặp ID trùng, thiếu trường ngôn ngữ, chuỗi trống hay kiểu dữ liệu không hợp lệ trong các trường được trích. Kết quả này được kiểm tra trên dữ liệu local; chưa phải đánh giá chất lượng ngôn ngữ.

Dữ liệu APK và kết quả lấy mẫu nằm trong thư mục `apk-localization/` đã được `.gitignore` loại khỏi Git. Khi đưa code lên GitHub, chỉ đưa module, tài liệu và tests giả lập; không đưa bản dịch nội bộ lên repo. Chuyển project `.lqa` riêng giữa Mac/Windows khi ứng dụng đã đóng.
