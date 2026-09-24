# Auto_ROK — điều phối hiện hành

Cập nhật 2026-09-24. Đây là mục điều phối duy nhất. ROOT giao gói theo
dependency, nhận handoff ngắn từ `workspace/agents/`, kiểm bằng chứng rồi
sửa tài liệu hiện hành tại chỗ. Git giữ lịch sử; không tạo bản v1/v2/final.

## Đích và quyền

Kết quả cuối là **LLM local dùng harness xác định để farm ROK mỗi ngày**.
FIRST DONE đã được người vận hành chốt là **một vòng năm đạo của một nhân vật
đã đi farm, có hậu kiểm queue 0→5/5**. New Troop tự điền cặp gợi ý của game;
harness giữ nguyên cặp và bấm March. Người vận hành ủy quyền một công việc GATHER lúc đầu;
không duyệt từng march. Hậu kiểm dừng tại 5/5, còn thời gian đào/về chỉ cần
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
`runtime-status.yaml` đã đối chiếu mã và bằng chứng ngày 2026-09-24; đây
là tình trạng bằng chứng, không phải quan sát game hôm nay. Lần 5/5 cũ là
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
đều PASS sau tích hợp. `character_id` vẫn là khai báo operator, chưa có
nhận dạng UI lúc bắt đầu; `--gather-job --arm-live` tiếp tục bị chặn. FIRST
DONE chưa live-proven hay đạt 5/5 tự chủ.

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

## Gói hiện hành: F3-B closeout sau resume, vẫn offline

[F2-A journal](../workspace/agents/f2a-verification-journal/tho_dung/HANDOFF.md)
đã sửa đủ ba lỗi mà [review độc lập](../workspace/agents/f2a-verification-journal/kiem_luat/HANDOFF.md)
nêu: giữ timestamp trước dispatch qua restart, lưu proof COMPLETE/VERIFIED để
phục hồi journal idempotent sau crash và kiểm tuổi baseline ngay trước input.
Journal còn cấm dùng lại frame và yêu cầu thời điểm quan sát tăng giữa hai lượt.
[F2-B coordinator](../workspace/agents/f2b-five-march/tho_dung/HANDOFF.md)
chọn năm `run_id` cố định từ journal VERIFIED, kiểm checkpoint từng lượt và
chỉ báo đóng job khi plan hợp lệ cùng closeout đã ghi. ROOT đã đối chiếu mã,
chạy toàn bộ pytest, graph, NNC và liên kết docs: PASS. Đây là **WIRED offline**
cho CLI một tick, không chứng minh game thật. [Nghiên cứu seam](../workspace/agents/f2-five-march/nghien_cuu/HANDOFF.md)
giải thích vì sao runner vẫn xử lý từng occurrence; [character scope](../workspace/agents/f2-character-scope/nghien_cuu/HANDOFF.md)
xác nhận UI identity còn thiếu.

Graph có node `gather_job_coordinator`; CLI gọi **một tick** mỗi lần.
[F2-C driver](../workspace/agents/f2c-job-driver/tho_dung/HANDOFF.md) nay nối
bounded ticks qua CLI canonical, dừng khi không chắc và ghi report append-only.
Issuer tạo launch spec riêng để một lần cấu hình đủ tham số tài nguyên; driver
kiểm SHA-256 của artifact quyền, danh tính và digest catalog trước tick. Test
synthetic đi từ driver qua CLI, MissionRunner và journal thật cho năm `run_id`
và 0→5/5. [Review độc lập](../workspace/agents/f2c-driver-review/kiem_luat/HANDOFF.md)
đã chấp nhận hai bản sửa: không còn artifact quyền mồ côi khi launch spec lỗi,
và tick báo lỗi không thể đóng job. Trường hợp restart sau lượt thứ năm được
kiểm qua journal/checkpoint/closeout bền, không March lần sáu. Hai mươi test
F2-C tập trung, toàn bộ pytest, graph, NNC đi kèm, 156 liên kết và diff check
đều PASS; mức **WIRED offline**. Trace cô lập input hiện gắn với
`run_id` của một occurrence, trong khi job có năm `run_id`; đây là preflight
cần nối theo job, không phải lý do hỏi duyệt từng march. [F3 audit](../workspace/agents/f3-first-done-audit/root/HANDOFF.md)
đã được ROOT nhận ở mức `IMPLEMENTED` offline sau review độc lập: nó đối chiếu
proof qua verifier canonical, report qua thứ tự/tick count, revoke và nguồn
đội hình. Mười test audit tập trung và full suite PASS; verdict chỉ là
`OFFLINE_REPLAY_PASS` hoặc `BLOCKED`, không nâng live.
Auditor chưa được driver gọi tự động và hiện chỉ nhận đủ năm slot trong một
attempt; [gói F3-B closeout sau resume](../workspace/agents/f3b-resumable-closeout/root/BRIEF.md)
là bước tích hợp kế tiếp.
Projection per-tick đã lưu readiness, frame/hash, client và thời điểm quan sát;
chín test `test_gather_replay_evidence.py` PASS, kể cả ca hai writer tranh
file cùng tên không thể ghi đè. Projection này chưa phải
closeout hay live proof.
`scripts/create_gather_job.py` tạo artifact quyền khởi đầu từ scope operator và
catalog GATHER biên dịch, không ghi đè; launch spec tách riêng không cấp thêm
quyền. Đây chỉ là đường cấp artifact, chưa chạy job hay mở quyền input.

- `owned_nodes`: journal xác minh của `gather_job_store`,
  `post_action_verification`, điều phối `mission_runner`/`gather_cli` và
  `gather_runtime_evidence`.
- `upstream_dependencies`: reservation/guard F1-B, client + New Troop fact
  F1-C, queue provenance, MissionEngine verifier một occurrence hiện có.
- `downstream_consumers`: audit FIRST DONE và một live occurrence riêng sau này.
- `acceptance_evidence`: replay 0→1→2→3→4→5/5 trên năm `run_id` khác nhau,
  mỗi lượt có receipt và frame hậu kiểm mới cùng job/client/nhân vật; restart,
  revoke, duplicate, stale, skip và kết quả không chắc đều fail closed. Test
  cấu trúc chứng minh CLI dùng journal, graph PASS, không phát input thật.
- `known_blockers`: archive chưa có mốc 0/5 hợp lệ; `character_id` chưa đọc từ
  UI; host isolation còn gắn từng run ID.
  Audit chưa được driver gọi tự động hoặc nhận chuỗi attempt sau resume.
  Các khoảng trống này chặn live nhưng
  không chặn replay offline.
- `graph_delta_expected`: queue baseline → MissionEngine VERIFIED → journal
  năm transition → quyền mở lượt kế → closeout 5/5. Không tạo motor song song.

Tiếp theo ROOT nối F3 audit với chuỗi attempt có thể resume, rồi đóng hợp đồng
preflight cấp job theo [nghiên cứu F4](../workspace/agents/f4-job-live-preflight/nghien_cuu/HANDOFF.md);
chỉ sau đó mới xét một lần thu baseline/nhân vật có provenance.
`runtime-status.yaml` vẫn để mục tiêu
`UNIMPLEMENTED`; không lấy synthetic 0→5 làm live proof. Game hiện có thể tắt.
Gói F2 dùng artifact/replay offline; chỉ cần mở lại khi phải thu một frame
baseline/nhân vật có provenance cho preflight live.
