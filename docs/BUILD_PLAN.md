# Auto_ROK — kế hoạch xây dựng hiện hành

[GOAL](GOAL.md) xác định FIRST DONE; [PRD](PRD.md) xác định nghiệm thu;
[SRS](SRS.md) xác định mệnh đề kỹ thuật; [engineering graph](../config/engineering_graph.yaml)
xác định authority node. Mức đã chứng minh chỉ lấy từ
[runtime-status](../runtime-status.yaml) và [COMPLETION_AUDIT](COMPLETION_AUDIT.md).
Kế hoạch này là thứ tự việc cần làm, không phải quyền chạy live.

## Đường FIRST DONE

Một công việc GATHER cho một nhân vật đã đăng nhập: người vận hành ủy quyền
một lần, harness giữ cặp New Troop do game tự điền rồi bấm March cho từng đạo,
hậu kiểm hàng đợi 0→1→2→3→4→5. Đạt 5/5 thì đóng vòng; ước lượng
đào/về là metadata, không chờ quân về. Không có duyệt từng march. B003/R3 là
đường benchmark/repetition riêng; G6/endurance và 24 giờ thuộc mốc farm hằng
ngày sau FIRST DONE.

Mỗi gói được giao với `owned_nodes`, `upstream_dependencies`,
`downstream_consumers`, `acceptance_evidence`, `known_blockers` và
`graph_delta_expected`. Agent nộp hồ sơ dưới `workspace/agents/`; ROOT kiểm
và tích hợp. Code/replay offline không nâng claim live.

## F0 — Đối chiếu cặp New Troop tự điền

**Owned nodes:** `live_capture`, `observation_projection`,
`gather_fact_extractor` (khảo sát, chưa đổi input path).

**Upstream:** frame New Troop có provenance và xác nhận của người vận hành rằng
game tự điền cặp. [Audit archive M7](../workspace/agents/first-done-recon/nghien_cuu/HANDOFF.md)
thấy `CREATE_NEW_TROOP` rồi `MARCH_WITH_CURRENT_SELECTION` không có input
chọn chỉ huy trong log, cùng frame có cặp đã điền. Điều này đủ làm bằng chứng
thiết kế về game-populated selection, không chứng minh ranking nội bộ “best”.
Capture ngày 2026-09-23 chỉ thấy CITY_VIEW. **Downstream:** F1 parser và policy.

**Đầu ra:** bản kiểm kê frame/ROI cặp đã điền, action mở New Troop và March,
character/queue, cùng giới hạn claim dưới `workspace/agents/`.

**Nghiệm thu:** archive có frame New Troop cặp đã điền và trace không chọn
chỉ huy; ca âm thiếu/không rõ cặp được liệt kê; không có input hay model call
trong khảo sát. F0 đã đạt mức survey offline, không chứng minh live mới.

## F1 — quyền job và New Troop readiness offline

**Upstream:** F0 và [SESSION_AUTHORITY](SESSION_AUTHORITY.md). **Downstream:**
`policy_overlay`, canonical `gather_cli`, input guard và F2.

F1-A đã tạo `gather_job_authority` cho catalog GATHER và precondition March.
F1-B đã thêm artifact loader, ledger reservation/revoke và
`gather_job_input_guard`, rồi nối opt-in vào CLI. Test synthetic dùng runner
thật và actuator giả để chứng minh đường job được tiêu thụ; no-game guard tests
từ chối stale/wrong/expired/revoked/duplicate trước actuator. Đây là wiring
offline, không phải live proof. CLI cố ý chặn `--gather-job --arm-live`.

**F1-C1/C2 đã nối offline:** job lưu HWND/PID/process path từ capture đầu và
kiểm ở các frame tiếp theo lẫn ranh giới input. `gather_fact_extractor` tạo
fact New Troop chỉ từ ảnh có hash khớp, OCR/target cùng frame, hai vùng chân
dung có hình, quân đã chọn và nút March hiện hành. Bốn ảnh New Troop archive
đọc dương; ca thiếu, stale, sai client, nút xám và chân dung trống là test
tổng hợp, không phải quan sát game thật. CLI synthetic dùng MissionRunner và
actuator giả đã tiêu thụ fact và guard; toàn bộ pytest, graph, NNC validator
PASS. Revoke hoặc frame/job hết hạn trong lúc đọc ledger đều chặn trước input.
Đó là `WIRED` offline, chưa chứng minh live. Không gửi input đổi chỉ huy.

**F1-C còn thiếu trước live:** `character_id` của CLI vẫn chỉ là cấu hình.
[F4-A1 attestation](../workspace/agents/f4a-startup-attestation/root/VALIDATION.md)
đã triển khai artifact xác nhận một lần ràng job/frame/client/thời điểm ở mức
offline; driver/tick chưa tiêu thụ và chưa có artifact trên frame thật. Ảnh âm
New Troop thật chưa có. Reader
queue đã đọc đúng các snapshot 1/5–5/5 nhưng chưa có 0/5 được hỗ trợ từ ROI
march queue. Chuỗi OCR `0/5` trong quest panel là mồi nhử, không phải baseline.
Nghiệm thu phần còn lại cần xác nhận nhân vật khởi đầu và queue 0/5 từ frame có provenance,
không cần duyệt từng march. Quyền khởi đầu không cần Windows Hello trong ranh
giới same-user local; nếu threat model đổi thì mở issuer riêng.

## F2 — Nối canonical runner và hậu kiểm năm lượt

**Owned nodes:** `gather_cli`, `mission_engine`, `policy_overlay`,
`post_action_verification`, `mission_store`, `gather_runtime_evidence`.

**Upstream:** F1 và queue/current-frame facts. **Downstream:** FIRST DONE
audit và lần live được ủy quyền sau này.

**Việc:** đi qua đường input guard hiện có, không tạo motor song song. Trước
mỗi march đọc New Troop readiness và quyền từ frame mới; sau dispatch đòi queue tăng một,
ghi `DISPATCHED` và `VERIFIED` riêng, khóa retry khi kết quả chưa rõ. Bắt
đầu tại 0/5, đóng sau năm postcondition tới 5/5.

Chia theo dependency: F2-A ghi journal VERIFIED/recovery; F2-B chọn slot và
gọi canonical runner một tick; F2-C điều khiển bounded ticks/occurrences của
cả job từ một lần khởi đầu. Gói preflight sau F2-C phải ràng bằng chứng cô
lập input vào job thay vì buộc người vận hành xác nhận mỗi slot. Các phần này
vẫn offline cho đến khi preflight live có nguồn được kiểm riêng.

**Nghiệm thu:** replay 0→5 và failure matrix (missing frame, queue không
tăng, wrong character, timeout, restart/duplicate); structural wiring test
chứng minh CLI thật dùng fact/guard. Graph PASS. Không kết luận live từ replay.

## F3 — Audit offline và live validation có scope

**Owned nodes:** FIRST DONE acceptance audit, `gather_runtime_evidence`,
`runtime-status` chỉ khi có bằng chứng mới.

**Upstream:** F0–F2. **Downstream:** quyết định release.

**Việc:** audit chỉ nhận năm hậu kiểm mới và quyền công việc khớp, phân biệt
manual intervention với autonomous run, report ước lượng có nguồn. Sau focused
tests, ROOT mới lập một occurrence live có scope cụ thể; không dùng approval
B003/R3 cũ và không suy quyền từ tài liệu. Live validation giữ preflight
foreground/current frame/input isolation và stop condition. Một vòng đạt
FIRST DONE ở mức `LIVE_PROVEN_ONCE`; repetition cần occurrences mới, stable
cần cửa sổ vận hành riêng.

**Nghiệm thu:** offline validator phát hiện stale/mismatch/receipt-only và
thiếu 1 trong 5 postconditions; live chỉ được nâng theo artifact thật. Đây
không phải lệnh chạy game ngay.

## Sau FIRST DONE — farm hằng ngày

Quan sát `Returning → HOME`, nạp lại slot, theo dõi và duy trì buff, rồi đo
chu kỳ 24 giờ. Positive return/home/buff evidence hiện thiếu; archive chỉ
cho thấy trạng thái `Gathering` và một tab BOOSTS có Resource Pack
([inventory](../workspace/agents/p1-continuity-evidence/nghien_cuu/HANDOFF.md)).
P1-A hiện mới chiếu `Gathering` cho một layout offline. Local LLM edge chỉ
chọn candidate đã lọc ở bất định thật; benchmark B003/holdout đo vai trò
model riêng, model cụ thể là cấu hình động. Multi-character, order, alliance,
delivery/tài sản và tối ưu hóa dài hạn mở sau đường một nhân vật.

Các gói được kích hoạt theo upstream và sự kiện completion/blocker; không
polling, sleep-retry hoặc hardcode model của ROOT/agent trong repo.
