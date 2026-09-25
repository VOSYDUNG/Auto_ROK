# Auto_ROK — điều phối hiện hành

Cập nhật 2026-09-25. Đây là mục điều phối duy nhất. ROOT giao gói theo
dependency, nhận handoff ngắn từ `workspace/agents/`, kiểm bằng chứng rồi
sửa tài liệu hiện hành tại chỗ. Git giữ lịch sử; không tạo bản v1/v2/final.

## Đích và quyền

Kết quả cuối là **LLM local dùng harness xác định để farm ROK mỗi ngày**.
FIRST DONE đã được người vận hành chốt là **một vòng năm đạo của một nhân vật
đã đi farm, có hậu kiểm queue 0→5/5**. New Troop tự điền cặp gợi ý của game;
harness giữ nguyên cặp và bấm March. Người vận hành ủy quyền một công việc GATHER lúc đầu;
đồng thời xác nhận nhân vật đang mở một lần; không duyệt từng march. Xác nhận
khởi đầu phải gắn với job/frame/client/thời điểm, không đòi OCR tên nhân vật.
Hậu kiểm dừng tại 5/5, còn thời gian đào/về chỉ cần
ước lượng có nguồn nếu ghi. Return/refill, buff và 24 giờ thuộc mốc farm
hằng ngày sau FIRST DONE. [GOAL](GOAL.md) sở hữu định nghĩa mốc,
[PRD](PRD.md) sở hữu nghiệm thu, [SESSION_AUTHORITY](SESSION_AUTHORITY.md)
sở hữu hợp đồng quyền công việc đề xuất.

Kiểm guard nội bộ ở mỗi lượt không phải operator approval. B003 là đường
benchmark/R3 cũ, không thành cổng duyệt năm march. Hành động tài khoản,
mật khẩu, xóa tài khoản, tiêu gem/item, chuyển tài sản hoặc ngoài catalog
GATHER không được ủy quyền bởi công việc này. Model local là cấu hình động;
LLM chỉ chọn một candidate đã lọc ở điểm bất định thật và không được phát
input hay thay cặp game gợi ý. Model ROOT do người dùng chọn trong phiên;
vai/model/effort của agent được quyết định theo gói và khả năng thực tế,
repo dùng profile `inherit`, không ghim tên model.

## Bản đồ nguồn thẩm quyền

| Vấn đề | Nguồn hiện hành |
|---|---|
| Mục đích và ranh giới | [PROJECT_DECLARATION](PROJECT_DECLARATION.md) |
| FIRST DONE và G1–G6 | [GOAL](GOAL.md) |
| Sản phẩm, kỹ thuật, thứ tự gói | [PRD](PRD.md), [SRS](SRS.md), [BUILD_PLAN](BUILD_PLAN.md) |
| Biên quyền công việc và gameplay LLM | [SESSION_AUTHORITY](SESSION_AUTHORITY.md), [LLM_GAMEPLAY_SPEC](LLM_GAMEPLAY_SPEC.md) |
| Node/edge/blocker | [engineering graph](../config/engineering_graph.yaml), [protocol](GRAPH_ENGINEERING.md) |
| Capability đã chứng minh | [runtime-status](../runtime-status.yaml) |
| Audit artifact lịch sử và gap | [COMPLETION_AUDIT](COMPLETION_AUDIT.md) |
| Đội repo và phương pháp | [team](../.codex/team.json), [AGENT_OPERATIONS](AGENT_OPERATIONS.md) |
| Kiến trúc và nguồn nhập | [DESIGN_BRIEF](DESIGN_BRIEF.md), [CONSOLIDATION](CONSOLIDATION.md) |

[ROADMAP_STATUS](ROADMAP_STATUS.md) chỉ điều hướng; [COVERAGE](COVERAGE.md)
là snapshot lịch sử. Yêu cầu và passing unit test không chứng minh wiring
hay live; `DISPATCHED` không đồng nghĩa `VERIFIED`.

## Bằng chứng hiện có và giới hạn

Cơ sở mã trước các gói FIRST DONE:
`7855c6165846ac53ed88d18a2701237fbf4bc539` trên `master`.
Các link `workspace/` dưới đây là hồ sơ local bị Git ignore; clone khác cần
artifact tương ứng trước khi kiểm lại hash hoặc kết quả. Tài liệu Git chỉ giữ
claim và đường truy nguyên, không chép ảnh game thô.
`runtime-status.yaml` đã đối chiếu mã và bằng chứng offline đến 2026-09-25;
`head_basis` tại đó là commit F3-B, còn SHA trên là mốc trước các gói
FIRST DONE. Đây là tình trạng bằng chứng, không phải quan sát game hôm nay.
Lần 5/5 cũ là
`LIVE_PROVEN_ONCE` trong phạm vi có can thiệp, không phải
vòng năm đạo tự chủ. Audit G1–G5 chỉ PASS trên artifact 18–19/09; G6
endurance còn BLOCKED, nhưng G6 không phải điều kiện FIRST DONE mới.

[GATHER-EVIDENCE](../workspace/agents/gather-evidence/root/BRIEF.md) đã đối
chiếu offline source/artifact. [GATHER-AUDIT-CONSISTENCY](../workspace/agents/gather-audit-consistency/root/validation.json)
đã sửa audit G6 và kiểm 14 test, graph và reference; không nâng live claim.
[PROJECT-FOUNDATION](../workspace/agents/project-foundation/root/HANDOFF.md)
đã lập cơ cấu docs/team động. Các hợp đồng P0-A/B/C cũ cho phiên 24 giờ
([records](../workspace/agents/p0-session-authority-contract/root/HANDOFF.md))
là lịch sử thiết kế, **đã bị quyết định FIRST DONE mới thay thế**; không
đặt Windows Hello, issuer ledger hay refill/buff thành blocker vòng 5 đạo.
[P1-A Gathering projection](../workspace/agents/p1-observation-projection/root/validation.json)
mới `IMPLEMENTED` offline cho một layout Troops 1366×768, chưa chứng minh
return/home hoặc đường live.

[Audit cặp New Troop](../workspace/agents/first-done-recon/nghien_cuu/HANDOFF.md)
cho thấy canonical flow dùng `MARCH_WITH_CURRENT_SELECTION`; `troop_policy`
lưu approval B003 boolean. Trace M7 cũ mở New Troop rồi March mà không có
input chọn chỉ huy trong log; ảnh cho thấy cặp đã điền. Người vận hành xác
nhận đó là gợi ý game tự điền. Không cần chứng minh xếp hạng “best” riêng.
Giới hạn: archive không chứng minh không có can thiệp bên ngoài log.

[F1-A job scope](../workspace/agents/f1a-job-scope/root/HANDOFF.md) nay
`IMPLEMENTED` offline: contract một job tối đa 5 march và nhánh precondition
của `policy_overlay`, tách khỏi B003. [F1-B job wiring](../workspace/agents/f1b-job-wiring/root/HANDOFF.md)
đã thêm artifact loader, digest từ flow GATHER biên dịch, ledger cố định với
năm reservation bền cho năm `run_id`, revoke API và guard ở input boundary.
CLI có nhánh opt-in job; fixture synthetic chạy **MissionRunner thật** với
capture/host/actuator giả và dùng output guard. Cấp đã chứng minh cho nhánh
code này là `WIRED` offline, chưa live. `--gather-job --arm-live` vẫn bị chặn.
Full suite dùng `--basetemp` ngoài repo vì một test HUD dùng `tmp_path` để
xác minh đường dẫn ngoài `workspace/`. [Input seam](../workspace/agents/f1b-job-wiring/nghien_cuu/HANDOFF.md)
và [review độc lập](../workspace/agents/f1b-job-wiring/kiem_luat/HANDOFF.md)
ghi rõ hai lỗi đã sửa: kiểm lại host/time sau ledger I/O và bỏ khả năng đổi
ledger root để reset quota. Reservation không phải queue verification.

[F1-C archive survey](../workspace/agents/f1c-evidence/root/HANDOFF.md) đã
chạy reader canonical trên 416 ảnh 1366×768 trong `workspace/runs/`: các ảnh
1/5–5/5 được đọc, **không có 0/5 có provenance queue được hỗ trợ**. Chuỗi
`0/5` trong OCR cũ thuộc quest panel, không thể dùng làm baseline. Bốn ảnh
New Troop archive cho thấy cặp game đã điền; OCR đọc header, March và số
quân/Total Power nhưng bỏ sót số ở hàng Units. Các ảnh là snapshot độc lập,
không thành một vòng năm đạo. [F1-C client binding](../workspace/agents/f1c-client-binding/tho_dung/HANDOFF.md)
lưu HWND/PID/process path từ capture đầu vào ledger và kiểm lại qua các lượt,
kể cả trước input. Review độc lập phát hiện race revoke/thời gian sau reserve;
hai ca này đã được sửa, test xác nhận zero fake input và reservation vẫn tiêu.
[F1-C formation](../workspace/agents/f1c-formation-fact/tho_dung/HANDOFF.md)
tạo fact New Troop từ ảnh có hash, OCR/target cùng frame và vùng UI có đội
hình/nút March. Bốn ảnh archive dương và ca âm tổng hợp PASS; chưa có ca âm
game thật để đo layout chưa thấy. CLI synthetic dùng MissionRunner thật và
actuator giả đã tiêu thụ hai nhánh mới, mức **WIRED offline**. ROOT đã chạy
toàn bộ pytest, engineering graph, NNC team validator và `git diff --check`
đều PASS sau tích hợp. Đường F1-C vẫn chỉ dùng `character_id` cấu hình;
artifact xác nhận một lần của F4-A1 đã được triển khai offline nhưng chưa
được driver/tick tiêu thụ.
`--gather-job --arm-live` tiếp tục bị chặn. FIRST
DONE chưa live-proven hay đạt 5/5 tự chủ.

[Q0 trainer](../workspace/agents/q0-training-safety/tho_dung/HANDOFF.md) nay
chỉ ghi profile sau khi kiểm `capture.json` native, hash PNG và reader đọc
đúng nhãn operator; ghi bằng thay thế atomic có khóa một writer. [Kiểm chứng
ROOT](../workspace/agents/q0-training-safety/root/VALIDATION.md) ghi nhận review độc lập đã buộc sửa lệch
schema manifest; ROOT chạy 41 test queue tập trung và thử đọc một capture
archive qua hàm kiểm manifest, đều PASS. Mức chứng minh của công cụ là
`IMPLEMENTED` offline. Profile thật chưa được sửa, chưa có glyph `0` hoặc
frame march queue 0/5, nên baseline live vẫn thiếu.

ROOT đã thực hiện **một capture thụ động** game đang mở:
[run artifact](../workspace/runs/first-done-recon-20260923-01/run.json),
frame `rok-20260923T062455480372Z-27d5c66a70a5`, SHA-256
`27d5c66a70a50b842209b28e5849ddb4fc1671b2bfc55a3d502bc9b3fe3ef3fe`.
Capture/OCR báo `READY`; ảnh nhìn bằng mắt là màn thành phố, scene parser
không cho state hint và không thấy New Troop. Lần này không
kích hoạt cửa sổ, gửi keyboard/mouse, chạy mission tick hay gọi model.
`READY` chỉ chứng minh đường capture, không phải readiness để phát input.

Plugin `shin-agentic-work@personal` 0.1.0 có trong catalog phiên này;
[plugin check](../workspace/agents/gather-evidence/root/plugin-check.md)
và NNC validator phân biệt phương pháp điều phối với quyền live. Hồ sơ agent
lưu trong workspace, handoff theo graph, không polling/sleep-retry.
[Soát nhất quán tài liệu](../workspace/agents/first-done-doc-consistency/nghien_cuu/HANDOFF.md)
đã chỉ ra hai mô tả trạng thái cũ ở SESSION_AUTHORITY và graph; ROOT sửa tại
nguồn hiện hành. GOAL, PRD, runtime-status và COMPLETION_AUDIT vẫn giữ thẩm
quyền riêng, không lặp một claim nghiệm thu ở hai nơi.

## Gói hiện hành: F4-A2 nối xác nhận khởi đầu, vẫn offline

[F2-A journal](../workspace/agents/f2a-verification-journal/tho_dung/HANDOFF.md),
[F2-B coordinator](../workspace/agents/f2b-five-march/tho_dung/HANDOFF.md) và
[F2-C driver](../workspace/agents/f2c-job-driver/tho_dung/HANDOFF.md) đã nối
năm `run_id` ổn định qua CLI một tick, guard input và journal VERIFIED. Mức đã
chứng minh là `WIRED` offline: synthetic MissionRunner/CLI đi 0→5/5, không có
một công việc live tự chủ. Trace host cũ gắn từng occurrence, không đủ cho cả job.

[F3-B closeout](../workspace/agents/f3b-resumable-closeout/root/VALIDATION.md)
đã được ROOT nhận ở mức `WIRED` offline tại commit `314fb2c`: driver kiểm chuỗi
attempt trước tick, nối lượt VERIFIED mồ côi chỉ khi có proof duy nhất và
`verified_at` thuộc đúng attempt, rồi tự gọi auditor khi đạt 5/5. Nếu crash
sau terminal report nhưng trước verdict, lượt chạy sau chỉ audit report có
sẵn, không gọi tick thứ sáu. Đường closeout mặc định buộc có chuỗi attempt;
replay lịch sử không có chuỗi được đánh dấu không có thẩm quyền đóng job.
[Review độc lập bản WIP](../workspace/agents/f3b-resumable-closeout/kiem_luat/HANDOFF.md)
đã tìm bốn lỗi này; ROOT thêm ca âm, chạy 47 test tập trung, full pytest,
engineering graph, NNC và diff check đều PASS. Review cuối độc lập chưa chạy
vì ghế builder gặp giới hạn sử dụng; bằng chứng này chỉ cho wiring offline.
Report/verdict do harness tạo bằng exclusive-create; không tuyên bố chống
được một tiến trình local khác sửa file sau đó.

[F4-A1 attestation](../workspace/agents/f4a-startup-attestation/root/VALIDATION.md)
đã `IMPLEMENTED` offline: một assertion của operator gắn với job, ảnh native,
client, thời điểm và QueueIndicatorReader đọc 0/5. Driver/tick chưa dùng artifact,
fixture synthetic chưa tạo mốc 0/5 thật. `runtime-status.yaml` sở hữu mức
capability hiện hành và vẫn giữ FIRST DONE `UNIMPLEMENTED`.

- `owned_nodes`: consumer của `startup_character_attestation`, preflight
  `gather_job_driver` và đường `gather_cli` chạy trực tiếp.
- `upstream_dependencies`: F3-B attempt chain đã nhận, F4-A1 artifact/validator,
  job store revoke và client binding.
- `downstream_consumers`: năm tick dưới một job; preflight host F4-B sau đó.
- `acceptance_evidence`: cùng một đường artifact và digest cho năm `run_id`
  kể cả resume; driver kiểm trước khi tạo attempt và trước mỗi tick, CLI trực
  tiếp không đi vòng. Thiếu/sửa/sai job/client/nhân vật/hết hạn/revoke đều
  dừng trước tick; không hỏi operator từng march. Test structural chứng minh
  consumer thật, hai công tắc `--arm-live` vẫn chặn.
- `known_blockers`: profile queue thật thiếu glyph `0`, archive không có frame
  march-queue 0/5 được hỗ trợ; host trace hiện chỉ gắn một `run_id` và số
  input ngoài luồng bằng 0 là tự khai của recorder.
- `graph_delta_expected`: thay edge attestation→driver đang ghi `planned`
  bằng edge consumer thật, thêm attestation→gather_cli; giữ input guard cũ.

[Brief F4-A2](../workspace/agents/f4a-attestation-wiring/root/BRIEF.md) và
[nghiên cứu seam](../workspace/agents/f4a-attestation-wiring/nghien_cuu/HANDOFF.md)
đủ đầu vào để giao code offline. Sau đó [F4-B](../workspace/agents/f4b-host-trace/root/BRIEF.md)
tự thu trace mới cho đúng `run_id` trước mỗi tick, không thêm approval thủ công.
Một capture queue 0/5 có provenance và glyph đã kiểm chứng còn cần để cấp
attestation thật; chỉ mở game lại khi thực hiện gói live riêng cho việc đó.
Hiện game có thể tắt. Không chạy game, gửi input hoặc gọi endpoint model trong
gói offline này.
