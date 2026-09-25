# Quyền công việc GATHER cho FIRST DONE

Trạng thái: **hợp đồng quyền, client binding, recovery journal và bộ điều phối
năm lượt đã nối offline**. CLI có nhánh opt-in đọc job, lưu client đầu phiên,
reservation, VERIFIED riêng và guard trước input. Driver năm lượt chạy
replay synthetic qua CLI và hai lỗi review đã được sửa, kiểm lại offline. CLI vẫn từ
chối `--gather-job` cùng `--arm-live` vì chưa có preflight cấp job và bằng chứng
khởi đầu về nhân vật/queue dưới đây.
[GOAL](GOAL.md) sở hữu mốc FIRST DONE; [PRD §3.4](PRD.md) sở hữu nghiệm thu
sản phẩm. Tài liệu này chỉ định biên quyền cho một công việc.

## Ủy quyền một lần, thực hiện năm lượt

Người vận hành khởi tạo **một công việc GATHER cho một nhân vật đã đăng nhập**.
Phạm vi là đưa năm đạo đi farm và đóng vòng khi hậu kiểm hàng đợi đạt 5/5.
Không cần người vận hành duyệt từng march. Mỗi lượt vẫn phải qua kiểm tra nội
bộ về cửa sổ, nhân vật, khung hình, đội hình tự điền, target và hậu điều kiện; kiểm
tra này không phải một lần xin quyền mới. Một quyền khác cần thiết nếu đổi
nhân vật, chuyển tài sản, dùng gem/item, đổi mật khẩu, xóa tài khoản hoặc đi
ra ngoài catalog GATHER. Những hành động ấy không có trong công việc này.

Quyền B003 hiện có chỉ gắn một occurrence lịch sử và dùng cho benchmark/R3.
Nó không phải điều kiện duyệt từng lượt của FIRST DONE, và công việc FIRST DONE
không được đọc B003 cũ làm quyền. Local LLM cũng không phát hành hay mở rộng
quyền; nó chỉ có thể chọn ứng viên semantic hợp lệ ở điểm bất định thật.

## Dữ liệu tối thiểu cần ràng buộc

Artifact schema v1 hiện có đúng các khóa `schema_version`, `job_id`,
`mission_id=GATHER_RESOURCE`, `task_id`, `character_id`, `catalog_digest`,
`starts_at`, `expires_at`, `allowed_actions`, `max_marches=5`. Operator đưa
đường dẫn artifact khi khởi tạo job; loader kiểm catalog từ flow GATHER đã
biên dịch. `scripts/create_gather_job.py` tạo artifact offline đúng một lần từ
task/nhân vật/tài nguyên/hạn do operator nhập và digest/action do compiler
tính; file cũ không bị ghi đè. Lệnh này không quan sát game hay cấp live arm.
Ledger cố định dưới `workspace/checkpoints/gather-jobs` lưu client
binding HWND/PID/process path, reservation và revoke, tránh cấp lại quota
hoặc đổi client chỉ bằng đổi tham số CLI. Hạn công
việc là giới hạn an toàn, **không phải thời lượng 24 giờ bắt buộc**. Cấu hình
khởi tạo là hành động rõ ràng của người vận hành trên máy cùng user; FIRST DONE
không đòi thiết bị ký/Windows Hello. Nếu về sau điều khiển từ xa hoặc actor
không cùng ranh giới tin cậy, phải thiết kế xác thực issuer riêng.

Client/window được ràng trên capture đầu và kiểm lại tại từng quan sát, trước
input; test synthetic cho thấy đổi HWND/PID/path, revoke và hết hạn đều bị
từ chối. Người vận hành xác nhận nhân vật đang mở **một lần khi cấp job**;
preflight phải lưu job/nhân vật/frame/hash/client/thời điểm của xác nhận đó.
FIRST DONE không đòi OCR tên nhân vật từ UI. `character_id` hiện do CLI cấu
hình với nguồn `configured_single_character_scope`; riêng giá trị cấu hình
chưa phải bằng chứng xác nhận khởi đầu. Để mở live, còn thiếu artifact xác
nhận từ frame thật được driver tiêu thụ và chuỗi hậu kiểm live mới. Theo xác
nhận của người vận hành, UI queue bên phải **chưa xuất hiện trước đạo đầu**:
không đòi ảnh 0/5 và không suy OCR trống thành số 0 quan sát. Đạo đầu chỉ
được `VERIFIED` khi frame hậu kiểm mới đọc đúng 1/5; sai/thiếu thì dừng.

Trace cô lập input của đường live cũ gắn với một `run_id`; job FIRST DONE có
năm `run_id` xác định từ cùng một quyền khởi đầu. F4-B đã nối offline trace
thụ động mới cho từng tick còn mở, ràng đúng `run_id` và client đã attested,
được driver/CLI kiểm trước runner. Một xác nhận input quiescence ở đầu drive
không biến thành năm lần người vận hành duyệt March. Recorder hiện tự khai
`unexpected_input_events=0` và chỉ lấy foreground trước/sau capture, nên
chưa chứng minh độc lập rằng host không bị can thiệp xuyên suốt. Cho đến khi
có nguồn thực cho preflight và các blocker live được giải quyết,
`--gather-job --arm-live` vẫn bị
chặn.

Một dispatcher chỉ dùng action thuộc catalog GATHER đã biên dịch. Chuỗi lạ
trong artifact không tạo action mới. Store cục bộ lưu reservation bền; cùng
`job_id + run_id` hoặc frame không được reserve hai lần, tối đa năm run ID
khác nhau cho năm occurrence.
Khi input có kết quả không chắc chắn, giữ sequence ở trạng thái chưa rõ và
quan sát lại, không bấm lại theo suy đoán. Operator có thể stop/revoke công
việc; stop không xóa lịch sử đã ghi.

## Quy tắc dùng cặp New Troop tự điền

Người vận hành xác nhận New Troop **tự điền cặp game gợi ý**. Harness mở màn
mới trong đường GATHER, không gửi input đổi chỉ huy, và bấm
`MARCH_WITH_CURRENT_SELECTION` khi khung hiện tại cho thấy New Troop đã có
đội hình và nút March hợp lệ. Không cần đọc danh tính từng chỉ huy, tìm nhãn
“best” hay xếp hạng riêng. Thiếu đội hình, khung cũ, state mơ hồ hoặc có
can thiệp/đổi selection ngoài luồng thì trả `HOLD`/`UNKNOWN_STATE`; không
dispatch. B003 approval, cấu hình cứng hoặc đề xuất LLM không thay khung
hiện tại.

Guard yêu cầu `new_troop_formation_ready=True` cùng New Troop/March target
trên cùng frame, rồi kiểm lại hạn job, tuổi frame, client và cửa sổ sau khi
reserve. Extractor canonical nay tạo fact này từ ảnh/nhãn có hash cùng frame,
và đã qua bốn ảnh archive dương cùng test âm tổng hợp; chưa có ca âm thật để
đo khả năng nhận sai trên layout chưa thấy. `ALLOW` chỉ là đủ điều kiện;
receipt là `DISPATCHED`. Khung mới sau
march phải cho đúng số queue sau lượt đó với cùng nhân vật và job mới ghi
`VERIFIED`: đạo đầu đọc 1/5 khi UI xuất hiện, bốn lượt tiếp theo tăng
1→2→3→4→5. Queue cuối 5/5 mới đóng vòng
FIRST DONE. Nếu không đủ bằng chứng, đóng `BLOCKED` hoặc `UNKNOWN_STATE` cùng
lý do, không coi là đạt. Ước lượng thời gian đào/về, nếu có, ghi nguồn và sai
số; nó không thay observation và không trì hoãn việc đóng vòng.

## Evidence và đường triển khai

Mục tiêu mỗi lần đánh giá là lưu `job_id`, nhân vật, sequence, frame/hash, New
Troop sẵn sàng, action/target, quyết định và lý do, receipt, frame hậu kiểm
và kết quả. Ledger ghi VERIFIED sau hậu kiểm; bản sửa F2-A đã giữ timestamp
qua restart, phục hồi proof COMPLETE/VERIFIED sau lỗi journal và kiểm tuổi
baseline trước input ([handoff](../workspace/agents/f2a-verification-journal/tho_dung/HANDOFF.md)).
F2-B đã nối năm slot vào CLI một tick với closeout bền trên replay tổng hợp
([handoff](../workspace/agents/f2b-five-march/tho_dung/HANDOFF.md)). Chưa có
chuỗi năm lượt live được nghiệm thu. Reservation không phải một march
`VERIFIED`.
Không chép màn hình thô vào tài liệu Git; artifact nặng ở `workspace/`.

Graph hiện nối catalog/job → loader/store/client binding → `policy_overlay`,
fact New Troop từ frame hiện tại và `gather_job_input_guard` → input boundary.
Đường recovery journal và bộ điều phối năm postcheck 1/5→5/5 đã được
kiểm trên fixture offline; fixture cũ có baseline số 0 sẽ được thay bằng
marker job không mang quan sát queue trước đạo đầu. Driver nhiều tick đã nối qua CLI; F3-B kiểm chuỗi attempt
trước tick và tự gọi auditor đóng vòng ở mức `WIRED` offline
([kiểm chứng](../workspace/agents/f3b-resumable-closeout/root/VALIDATION.md)).
Artifact xác nhận ban đầu F4-A1 nay được driver và tick trực tiếp tiêu thụ,
kiểm trước attempt/tick và ghim cùng digest khi resume ở mức offline F4-A2
([kiểm chứng](../workspace/agents/f4a-attestation-wiring/root/VALIDATION.md)).
Preflight host cho cả job còn thiếu. Những bước này tiêu thụ `gather_runtime_evidence`;
không tạo đường input song song với canonical
`gather_cli`/`mission_engine`.

Nghiệm thu offline: fixture dương/âm cho New Troop có đội hình/March, màn
thiếu đội hình/nút March, frame cũ, sai nhân vật, action ngoài scope, hết hạn/revoke,
duplicate sequence, receipt không có postcondition, và chuỗi năm queue. Test
wiring chứng minh canonical entrypoint dùng guard và fact mới; graph validator
PASS. Mọi test offline chỉ chứng minh mức code/wiring, không chứng minh game
live hay cấp quyền cho một occurrence mới.
