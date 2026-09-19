# G003 — Tool trước, LLM sau, dựa trên game thật

Yêu cầu hiện hành: người dùng đã mở ROK trên Windows host để đội phân tích và xây tool. Lớp mission không được phụ thuộc endpoint8080 để duy trì nhịp. Goal vẫn là Computer Use/OCR hoàn chỉnh; local model là decision provider cho điều chưa chắc, không thay timer/checkpoint bằng một phiên chat kéo dài.

## Thứ tự triển khai mới

| Bậc | Sản phẩm cần có | Nghiệm thu |
|---|---|---|
| T0 | Discover target + capture cửa sổ thật, không kích hoạt/input | Đúng app/window, PNG có pixel game, clientbounds/DPI/time/hash, lỗi black/minimized/unsupported rõ |
| T1 | Tool OCR/vision/anchor thuần frame-in → candidates-out | Bbox/label/template có nguồn, không tọa độ desktop cố định; ambiguous/stale → NEEDS_DECISION |
| T2 | Mission tick/checkpoint/due/retry/cancel chạy không LLM | Chạy khi8080 tắt; dry-run không completed/issued; restart không lặp và không bỏ qua gate |
| T3 | Action backend không giành input + verifier | Một thao tác được cấp, đúng target/anchor mới; receipt rồi postframe mới; không “lệnh trả0=thành công” |
| T4 | Local decision provider + hội thoại | Mission gửi gói trạng thái/câu hỏi; model trả decision có schema; tool kiểm lại trước thực thi |

VM/guest là lựa chọn backend action, không phải điều kiện để bắt đầu T0/T1 trên host. Không dùng PostMessage/SendInput/foreground activation khi chưa vượt yêu cầu không chiếm input. Tool product được phát triển repo-local, không sửa helper Codex hoặc cài driver/đổi OS.

## Tool cũ được giữ lại phần nào?

Auto_ROK/main.py, Mouse_key.py: lấy tên workflow Get_rss_clan/Find_pit/change_account và ý nghĩa bước; không import hoặc replay chuỗi click. Avatar.py: giữ ý tưởng nhận dấu xanh bằng HSV/contour, chữ bằng OCR và ứng viên avatar bằng hình học; viết lại detector thuần ảnh. Territory_position đang vừa OCR vừa gửi phím/click, cần tách. Human.py logger chuột/phím không phải nguồn đầu vào thường trực cho sản phẩm này.

Tọa độ click phải suy từ bbox ứng viên trong frame cụ thể, có target/clientbounds/DPI và evidence. Tọa độ tương đối hardcode cũng không được coi là anchor. Nhãn/biểu tượng chưa xuất hiện trong ảnh thật chỉ là hypothesis, không tự calibrated.

## Mission sống theo nhịp

Persist mission definition, occurrence ID, due time/timezone, checkpoint, retry/backoff và reason cần quyết định. Runtime tick đánh giá một bước hữu hạn rồi trả quyền điều khiển; scheduler sau này gọi tick theo due/event thay vì vòng while click liên tục. State machine xử lý WAITING/OBSERVE/PLANNED/NEEDS_DECISION/AWAITING_VERIFICATION/COMPLETED/CANCELLED/FAILED theo evidence có thực. Tên trạng thái là hợp đồng mong muốn; xem evidence để biết phần đã triển khai.

Local LLM service được giữ **always-on ở trạng thái observer/idle**, nhưng không
nhận mission stream. Khi due, tool quan sát và áp rule đã kiểm; chỉ tình huống
mơ hồ/thay đổi mới gửi decision packet. Nếu endpoint tạm tắt, mission vẫn biết
nó đang đợi gì và giữ state; khi model trở lại, nhận brief ngắn gồm
graph/state/allowed tools/budget. Người dùng vẫn có thể quyết định hoặc hủy.
Tool không tự gọi cloud để vượt lỗi local.

## Thực nghiệm đang diễn ra

Root xác nhận cửa sổ MASS/Rise of Kingdoms thật bằng Computer Use. Native helper capture hai lần lỗi SetIsBorderRequired0x80004002; accessibility chỉ có pane, không có control game. [Microsoft](https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.graphicscapturesession.isborderrequired?view=winrt-26100) nêu property này từ build20348, cao hơn host19045. Đây là giới hạn của đường capture hiện tại, không phải game chưa mở.

Builder phát triển capture adapter thụ động riêng của sản phẩm tương thích Win10. [PrintWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-printwindow) là candidate target-only nhưng ứng dụng quyết định việc render, nên phải kiểm ảnh thực và không hứa hoạt động trên mọi game. WGC có thể dùng đường hỗ trợ Win101903 với feature detection; không bỏ qua consent hoặc xin borderless để né lỗi.

Chưa tự bật lịch hằng ngày/15giờ trong phiên này. Đợt này xây và đo tool; lịch thường trực chỉ được bật sau gate thực tế và phạm vi mission cụ thể.
