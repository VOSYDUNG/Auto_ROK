# Auto_ROK — điều phối hiện hành

Cập nhật 2026-10-03: audit cách coding/giao hàng từ source `main@4ea9567` và
artifact đã lưu. ROOT giữ quyết định/gói kế tiếp; [runtime-status](../runtime-status.yaml)
sở hữu mức chứng minh. Raw evidence/hồ sơ ở workspace, lịch sử sửa ở Git.

## Đích, quyền và nguồn canonical

FIRST DONE đã chốt trong [GOAL](GOAL.md)/[PRD](PRD.md): một job tự đưa năm đạo
của một nhân vật đi farm, giữ cặp New Troop game điền, hậu kiểm mới 1/5→5/5.
Không chờ quân về/buff/24 giờ, không cần frame 0/5 trước đạo đầu, không duyệt
mỗi March. Người dùng đã xác nhận nhân vật/quyền/focus một lần theo job;
guard client/frame/focus/quota kiểm kỹ thuật. [SESSION_AUTHORITY](SESSION_AUTHORITY.md)
sở hữu biên job/hỗ trợ ROOT, không mở hành động tài sản/account ngoài scope.
Mốc cuối là LLM local farm mỗi ngày; model chỉ chọn tại bất định có nghĩa.

| Thông tin | Nguồn sở hữu |
|---|---|
| Mục đích/biên | [PROJECT_DECLARATION](PROJECT_DECLARATION.md), [GOAL](GOAL.md) |
| Scope/nghiệm thu | [PRD](PRD.md); [SRS](SRS.md) là chi tiết kỹ thuật |
| Quyền | [SESSION_AUTHORITY](SESSION_AUTHORITY.md) |
| Node/edge | [graph](../config/engineering_graph.yaml), [protocol](GRAPH_ENGINEERING.md) |
| Mức đã đo/occurrence | [runtime-status](../runtime-status.yaml) |
| Phương thức đội/coding | [AGENTS](../AGENTS.md), [team](../.codex/team.json), [AGENT_OPERATIONS](AGENT_OPERATIONS.md) |
| Việc còn lại | [BUILD_PLAN](BUILD_PLAN.md) |
| Audit bằng chứng | [COMPLETION_AUDIT](COMPLETION_AUDIT.md); snapshot có ngày giữ riêng |

## Tình hình đã kiểm và giới hạn

FIRST DONE tự chủ vẫn **WIRED**. Job09 `f6-firstdone-20260928-09` hết hạn:
[attempt2](../workspace/evidence/gather/job-drives/28b1097c4dfd0fcd1383/attempt-000002.result.json)
6 tick/50,48 giây tới Drawer, zero reservations/VERIFIED, chưa March, không
closeout. Số zero là tiến độ job cũ, không phải occupancy hiện tại của game.
[Reproducer](../workspace/agents/workflow-audit/root/idle-replay.json) cho pure
driver dùng stored tick statuses tái hiện idle stop; không phát input hoặc
chứng minh E2E. Source chỉ nhìn tổng VERIFIED để reset idle.

Job06 có native 1/5→5/5 và closeout, được nhận assisted LIVE_PROVEN_ONCE bởi
[review](../workspace/agents/f6p-fresh-round/kiem_luat/CLOSEOUT_REVIEW.md).
Calibration/UI hỗ trợ giữa vòng không thành nghiệm thu tự chủ. Job07 hết hạn
3/3; job08 chỉ issuance, chưa có driver report. Không ghép proofs/quota, kéo
TTL hoặc dùng UI cũ để tiếp tục job. Runtime/profile/asset đều phải fixed khi
nhận một occurrence mới. Daily, return/refill/buff chưa đạt; host trace vẫn
self-report, không thành đo độc lập mọi input.

Git đã hợp nhất về `main`; source checkpoint 4ea9567 đã push, assets F6W có
trong checkout và mixed ledger scope ghim đủ schedule fields. Historical mixed
ledgers thiếu scope mới là evidence, không tự migrate/adopt. [Publication checks](../workspace/agents/git-main-publication/root/VALIDATION.md)
49 focused/native pass; broad 1.021 pass/13 native skips/1 journal failure.
Case đạt riêng không xóa failure hoặc chứng minh I/O ổn định.

## Audit phương thức và quyết định

[Audit](../workspace/agents/workflow-audit/root/AUDIT.md) kiểm cơ cấu tài liệu,
đường runtime, route legacy, test boundary, live/calibration sequence, Git/assets
và điều phối đội; không là review mọi nhánh gameplay hoặc security scan.
[Inventory](../workspace/agents/workflow-audit/root/inventory.json) và
[review](../workspace/agents/workflow-audit/kiem_luat/HANDOFF.md) ghi căn cứ;
[integration review](../workspace/agents/workflow-audit/kiem_luat/INTEGRATION_REVIEW.md)
và [validation](../workspace/agents/workflow-audit/root/VALIDATION.md) nhận phần tài liệu.
User chọn child GPT-6.1 Sol/high, fresh context, read-only offline. Reviewer
hoàn tất; researcher bị capacity, ROOT làm runtime audit, không fallback Luna/5.6.
ROOT giữ model người dùng; chưa sửa runtime hoặc gọi endpoint/game trong audit.

Kết luận: test mảnh/proof có ích nhưng city-start whole-cycle được ghép quá
muộn; idle contract dừng đường đang tiến; live tuning làm mất nghiệm thu tự
chủ. Cách sửa là giữ guards/provenance, đổi thứ tự và đơn vị giao hàng thành
trọn chu kỳ. BUILD_PLAN đã bỏ package chronology; AGENT_OPERATIONS giữ nhịp
reproducer→patch+consumer test→integration→freeze→whole-job→audit. Current audit/
protocol đã gỡ thiếu-node/CI/chain mâu thuẫn; snapshot và raw measurements giữ ngày.
Script legacy được dùng làm đối chiếu thứ tự/knowledge layout; báo cáo 2×4 của
người vận hành chưa benchmark lại, không chạy actuator cũ.

## Một gói kế tiếp: GATHER-CYCLE-REPAIR

Theo [BUILD_PLAN](BUILD_PLAN.md), owned `gather_job_driver`, `gather_cli`,
`gather_job_coordinator`, `gather_runtime_evidence`; upstream scope/attestation/
frame/profile/journal, downstream whole-job năm proofs/closeout. Chỉ mở
runner/store khi reproducer chứng minh integration cần. Expected graph delta:
valid navigation progress→driver liveness; không engine/actuator song song.

Đầu ra coding cần route CITY→Search→detail→Drawer→New Troop→March/postcheck đủ
năm slot qua compiler/runner/coordinator/driver thật với substitute offline.
Giữ idle/wall/tick bound cho stuck/oscillation, hậu kiểm pending March không
replay, và journal failure diagnostic/exact-proof recovery không input.
Acceptance phải gắn consumer thật, không tăng tick ceiling để giấu lỗi hoặc
lấy prepared COMPLETE thay route. Model/effort chọn theo chỉ định đang có và
availability, writer sở hữu disjoint scope; review guard/proof sau patch.

Sau offline acceptance mới lấy fresh startup và chạy một job fixed-source theo
quyền đã có, không brief/agent/calibration giữa các click. Năm fresh proofs và
closeout cùng occurrence mới đủ LIVE_PROVEN_ONCE; sau đó đo same-boundary
latency để quyết định persistent process, rồi return/refill/buff/daily/scale.
Chưa có baseline trọn vòng tự chủ nên không hứa ETA hoặc mức tăng tốc. Đội chạy
theo completion/blocker, không polling/sleep-retry. Không mở thêm mission trước
khi consumer FIRST DONE đã qua đường nghiệm thu.
