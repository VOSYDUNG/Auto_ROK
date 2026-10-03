# Auto_ROK — điều phối hiện hành

Cập nhật 2026-10-03 cho gói Git main publication, từ source basis `02bbff4`
và working tree đã đối chiếu. ROOT là brief điều phối duy nhất;
[runtime-status](../runtime-status.yaml) sở hữu mức chứng minh và occurrence.
Lịch sử sửa đổi ở Git; raw evidence và hồ sơ agent ở `workspace/`.

## Đích và quyền

Đích cuối là LLM local dùng harness farm ROK mỗi ngày. FIRST DONE thuộc
[GOAL](GOAL.md)/[PRD](PRD.md): một job đưa năm đạo đi, giữ cặp New Troop game
tự điền, hậu kiểm mới 1/5→5/5, không chờ đào/về, buff hoặc 24 giờ. Không đòi
frame 0/5 trước đạo đầu; ordinal job không phải quan sát số 0.
`DISPATCHED` khác `VERIFIED`.

Người dùng đã xác nhận `one-character`, foreground/quiescence và ủy quyền
trọn FIRST DONE; không duyệt từng March. Guard là kiểm kỹ thuật.
[SESSION_AUTHORITY](SESSION_AUTHORITY.md) sở hữu quyền job và hỗ trợ UI ROOT.
Không đổi tài khoản/mật khẩu/xóa, cặp tướng hoặc tài sản ngoài scope. Model
ROOT do người dùng chọn; model/effort của đội được chọn động theo gói.
Phiên hiện hành chỉ kiểm offline, commit/push và hợp nhất Git về một `main`;
không gửi input game hoặc gọi endpoint model.

## Nguồn canonical

| Vấn đề | Nguồn sở hữu |
|---|---|
| Mục đích/biên | [PROJECT_DECLARATION](PROJECT_DECLARATION.md), [GOAL](GOAL.md) |
| Yêu cầu/nghiệm thu | [PRD](PRD.md), [SRS](SRS.md) |
| Quyền | [SESSION_AUTHORITY](SESSION_AUTHORITY.md) |
| Thứ tự việc | [BUILD_PLAN](BUILD_PLAN.md) |
| Node/edge | [graph](../config/engineering_graph.yaml), [protocol](GRAPH_ENGINEERING.md) |
| Trạng thái đã chứng minh | [runtime-status](../runtime-status.yaml) |
| Audit/giới hạn | [COMPLETION_AUDIT](COMPLETION_AUDIT.md) |
| Đội/phương pháp | [team](../.codex/team.json), [AGENT_OPERATIONS](AGENT_OPERATIONS.md) |

## Kết quả thực tế và bằng chứng

FIRST DONE tự chủ vẫn ở mức **WIRED**. Job gần nhất
`f6-firstdone-20260928-09` đã hết hạn. ROOT đọc lại
[attempt 2](../workspace/evidence/gather/job-drives/28b1097c4dfd0fcd1383/attempt-000002.result.json)
và ledger: 6 tick, 0 reservations, 0 VERIFIED, không closeout. Driver dừng với
`fresh observation did not advance within idle bound` dù
[tick cuối](../workspace/evidence/gather/gather-07ed0e83c69b3ae96d94/revision-000006-1790580771145916300.json)
đã chuyển từ resource detail sang Drawer. `drive_job` hiện đếm các tick chưa
tăng tổng VERIFIED là idle, kể cả điều hướng đang tiến triển. Đây là blocker
cần regression offline, không phải bằng chứng phải duyệt mỗi March. Attempt
đầu bị focus preflight chặn; ROOT đưa cửa sổ foreground trước attempt 2.
Không dùng lại TTL, quota hoặc startup cũ. Số 0 trong ledger là tiến độ job,
không phải quan sát occupancy hiện tại của game.

Job08 được cấp nhưng chưa có driver report. Job07 hết hạn với 3/3; recovery và
sửa nguồn sau đó không tạo đạo thứ tư. Job06 có native 1/5→5/5, đúng lịch và
quota đóng, được nhận **assisted LIVE_PROVEN_ONCE** bởi
[review](../workspace/agents/f6p-fresh-round/kiem_luat/CLOSEOUT_REVIEW.md).
Can thiệp modal và calibration giữa vòng loại trừ nghiệm thu tự chủ. Các
proofs được giữ nguyên; không ghép quota/proof giữa các job. Daily farm và
LLM local chưa đạt nghiệm thu. Audit OFFLINE_REPLAY_PASS chỉ chứng minh cấu
trúc/provenance; verdict không tự tuyên bố FIRST DONE live.

## Gói đã kiểm chứng và phạm vi hiện hành

[GATHER-EVIDENCE](../workspace/agents/gather-evidence/root/BRIEF.md) đã đối chiếu
shin-agentic-work@personal 0.1.0 cùng NNC đi kèm. F1–F4 nối job, guard, client,
formation, journal, coordinator, attestation và trace vào CLI canonical.
F6-E/K/L/M sửa exact-proof recovery, pending admission, immutable observation
artifacts và diagnostic chain; hồ sơ ở `workspace/agents/`.

F6-P/Q/R/S nối numeric Drawer baseline, capture không cursor và glyph queue
3/4 có nguồn đo. F6-U kiểm Units ROI và readiness low-fill;
[F6-V](../workspace/agents/f6v-navigation-recovery/root/VALIDATION.md) chỉ gỡ
exact pending CREATE_NEW_TROOP, không gỡ pending March hoặc tăng tiến độ.
F6-O continuation vẫn deferred, không có receipt gia hạn.

[F6-W](../workspace/agents/f6w-farm-visual/root/VALIDATION.md) đã được ROOT và
[reviewer](../workspace/agents/f6w-farm-visual/root/IMPLEMENTATION_REVIEW.md)
kiểm offline: matcher hiện hành nhận nút Search và ít nhất hai biểu tượng
tài nguyên, không cần nhãn Barbarians. Tám stored native cases và focused
wiring/provenance tests hỗ trợ **WIRED**, không chứng minh trọn vòng live.
Correlation không phải xác suất hoặc quyền input. Provider dùng current
frame/hash/time/client/layout, không bịa OCR hoặc tạo click target.

Gói hiện hành [Git main publication](../workspace/agents/git-main-publication/root/BRIEF.md)
đóng gói sáu crop nhỏ tại [farm assets](../config/assets/farm_search/README.md)
với hash/calibration hiện hữu, giới hạn matcher vào thư mục asset canonical
hoặc `workspace/runs`. Synthetic recognition và path refusal kiểm khả năng
clone chạy detector; raw screenshot/history không được đưa lên Git.
ROOT sở hữu profile/matcher publication, graph/docs/runtime và Git; reviewer
read-only kiểm dispatch/proof/audit. Inherit model/effort, context tối thiểu,
autonomy offline. Agent completion/blocker kích hoạt kiểm chứng, không polling.

Kết quả kiểm hiện hành và giới hạn được ghi tại
[VALIDATION](../workspace/agents/git-main-publication/root/VALIDATION.md).
49 test tập trung đạt; bộ rộng có 1.021 pass, 13 native skips được kiểm riêng,
1 audit fixture journal failure. Case lỗi đạt một lần khi chạy riêng; không
coi đó là xóa failure hoặc chứng minh journal ổn định.
Một lần test có lỗi không được gọi là toàn suite PASS. Host trace vẫn là
`recorder_self_report_only`, chưa đo độc lập toàn bộ input. Không nâng
IMPLEMENTED/WIRED thành REPEATABLE/STABLE bằng test hoặc ảnh lịch sử.

## Bước tiếp theo

Nhánh canonical của bản hợp nhất là `main`, giữ lịch sử và evidence. Gói kế
tiếp sửa idle budget offline: ghi nhận tiến triển điều hướng bằng
checkpoint/action/verification có provenance, vẫn chặn lặp thật, không replay
March mơ hồ hoặc tăng quota. Kiểm regression đường city→Search→detail→Drawer→
New Troop→March và negative stuck/reobserve. Chỉ sau nghiệm thu mới cấp startup
job mới theo quyền đã có, chạy cả năm đạo trong một driver; không brief hoặc
gọi agent cho từng nút. Khi dừng mới xử lý blocker, khi kết thúc mới audit tổng.
Source cố định và năm proofs mới đủ nhận FIRST DONE LIVE_PROVEN_ONCE.
