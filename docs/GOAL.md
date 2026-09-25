# Mục tiêu Auto_ROK

Nguồn mục đích và ranh giới: [PROJECT_DECLARATION](PROJECT_DECLARATION.md).
Nguồn yêu cầu/điều kiện sản phẩm: [PRD](PRD.md). Nguồn claim đã chứng minh:
[runtime-status.yaml](../runtime-status.yaml) và [COMPLETION_AUDIT](COMPLETION_AUDIT.md).
Tài liệu này sở hữu **mục tiêu hiện hành, FIRST DONE và định nghĩa G1–G6**;
không ghi lại tiến độ thực thi như một bản thứ hai.

## Kết quả muốn đạt

LLM local của người vận hành dùng một harness xác định để farm Rise of Kingdoms
mỗi ngày. Harness quan sát, dựng fact có nguồn, lọc hành động, chặn input,
checkpoint và xác minh; LLM chỉ nhận bài toán lựa chọn nhỏ, có thể từ chối.
Không lấy việc gọi được model hay một lần điều quân làm bằng chứng đã đạt kết quả.

## FIRST DONE — một vòng 5 đạo đã đi farm

Trên một client ROK hiển thị và đã đăng nhập, ở một máy Windows, harness tự
đưa **năm đạo của cùng một nhân vật** đi farm trong một công việc GATHER được
người vận hành cấu hình/ủy quyền lúc bắt đầu. New Troop **tự điền cặp chỉ huy
theo gợi ý của game**; harness giữ nguyên cặp đó, bấm March rồi hậu kiểm.
Người vận hành xác nhận nhân vật đang mở **một lần** khi cấp job; bằng chứng
khởi đầu ràng xác nhận đó với frame, client và thời điểm. Không bắt buộc OCR
tên nhân vật từ UI cho FIRST DONE, và cấu hình `character_id` đơn lẻ chưa phải
bằng chứng xác nhận này.
Nếu cặp trên màn hiện tại trống/không đọc được hoặc bị đổi ngoài luồng thì
dừng lượt, không tự xếp hạng thay game. Không duyệt thủ công từng march.

Vòng hoàn tất khi cả năm lệnh điều quân có hậu kiểm bằng quan sát mới: giao
diện hàng đợi bên phải chỉ xuất hiện sau đạo đầu, và lần hậu kiểm đầu phải đọc
đúng 1/5. Các lượt tiếp theo đọc 2/5, 3/5, 4/5 rồi 5/5 cho đúng nhân vật/công
việc. Không đòi một frame 0/5 không tồn tại và không biến việc thiếu UI trước
đạo đầu thành một số 0 đã quan sát. Biên nhận
input hoặc ảnh 5/5 của occurrence cũ không đủ. Thời gian đào/về có thể được
ước lượng và ghi rõ nguồn, độ bất định; **không phải chờ quân về** để đạt FIRST
DONE. Quyền công việc chỉ bao phủ đường GATHER cần để đưa năm đạo đi; hành động
ngoài phạm vi hoặc rủi ro cao cần quyền riêng. Xem [PRD §3.4](PRD.md) và
[SESSION_AUTHORITY](SESSION_AUTHORITY.md).

Đây là mục tiêu cần xây và chứng minh, chưa phải quyền phát input hiện có.
[runtime-status](../runtime-status.yaml) giữ mức đã chứng minh; lần 5/5 lịch sử
có can thiệp không chứng minh vòng tự chủ này. Duy trì farm 24 giờ, phát hiện
quân về, nạp lại, buff và nhiều nhân vật là các mốc **sau** FIRST DONE. Lát cắt
kỹ thuật hiện hành vẫn là `GATHER_RESOURCE` một nhân vật.

## Hợp đồng quyết định

Khi có quan sát tươi, gắn nguồn gốc, và nhiều hơn một lựa chọn hợp lệ thật sự,
harness gửi cho LLM local ngữ cảnh tối thiểu cùng các `ActionChoice` đã lọc.
LLM được chọn đúng một ứng viên hiện có, trả `NEEDS_DECISION`, hoặc báo
`retraining_required` khi giao diện đã đổi. Ứng viên bịa, sai format, hết hạn
hoặc response chậm đều fail closed. Harness không đưa toạ độ thô, thông tin
ẩn, quyền phát input, đồng hồ hoặc quyết định lịch cho model. Model local cụ
thể là cấu hình chạy có thể thay thế; nó không định nghĩa mục tiêu hay quyền.

Dịch vụ có thể sẵn sàng nhưng không bắt buộc nhận câu hỏi ở mỗi tick. Cặp
New Troop tự điền là fact cần đọc, không phải bài toán xếp hạng cho model. Huấn
luyện/benchmark mức tham gia của LLM là nhánh đo riêng; FIRST DONE không đặt
số lần gọi model tùy ý làm điều kiện cho một đường deterministic đã đủ rõ.

## G1–G6 — audit lịch sử và cổng cho đợt live tương ứng

| Cổng | Điều kiện phải có bằng chứng |
|---|---|
| G1 | Cô lập input trên host Windows thật, đúng cửa sổ/foreground, từ chối khung cũ, có huỷ/khôi phục và không có input ngoài ý muốn |
| G2 | CPU/OCR/trạng thái đạt trên holdout mà không hạ chuẩn grounding hoặc phụ thuộc GPU |
| G3 | Biên `NEEDS_DECISION` của LLM local được đo trên ca rời khung; gọi được endpoint không đủ |
| G4 | Audit hiện hành kiểm quyền B003 gắn một occurrence lịch sử; quyền cũ không dùng lại. B003 là đường benchmark/R3, không phải duyệt từng march của FIRST DONE |
| G5 | GATHER có giới hạn chứng minh Queue used +1 bằng quan sát tươi, với cancel/resume/recovery đúng hợp đồng |
| G6 | Chỉ sau G1–G5, đủ lặp R3 và uỷ quyền tường minh mới xét endurance; G6 thuộc promotion endurance sau FIRST DONE |

`scripts/audit_goal_readiness.py` kiểm G1–G6 từ artifact đã lưu. Audit PASS trên
bằng chứng cũ không tự cấp quyền cho công việc mới. FIRST DONE cần quyền công
việc GATHER ban đầu và hậu kiểm 5/5 theo PRD, không đợi G6 endurance; G4 hiện
tại chỉ chứng minh phê duyệt của occurrence lịch sử. Không thay nó bằng cờ cho
phép chung.

## Ranh giới

Không Docker, VM, Hyper-V hay GPU; không đọc bộ nhớ tiến trình, chèn code, tác tử desktop tự do,
phát input từ model, tái sử dụng approval hoặc replay cũ. Mọi mục tiêu có toạ độ
phải được grounding từ khung hiện tại. `DISPATCHED` không phải `VERIFIED`.
Các nhánh mission khác chỉ mở khi có hợp đồng quan sát, chính sách, hành động
và xác minh riêng; xem [mission matrix](GAME_STATE_MISSION_MATRIX.md).
