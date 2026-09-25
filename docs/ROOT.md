# Auto_ROK — điều phối hiện hành

Cập nhật 2026-09-25. Đây là brief ROOT duy nhất. Hồ sơ agent và bằng chứng
nặng nằm trong `workspace/agents/` và `workspace/runs/`; Git giữ lịch sử thay
cho các bản báo cáo v1/v2/final. ROOT chỉ nâng trạng thái theo bằng chứng đã
kiểm, không theo kế hoạch hoặc kết quả test đứng riêng.

## Đích và biên quyền

Đích cuối là **LLM local dùng harness để farm ROK mỗi ngày**. FIRST DONE hiện
là **một job GATHER cho một nhân vật, tự điều đủ năm đạo đi farm và hậu kiểm
từng đạo**. Người vận hành cấp job và xác nhận nhân vật đang mở một lần, gắn
với job/frame/client/thời điểm. Không duyệt từng March. New Troop đã có cặp
game tự điền; harness giữ nguyên và dùng nút March, không tự chọn lại chỉ huy.

Theo xác nhận mới nhất của người vận hành, **UI queue bên phải chưa xuất hiện
trước đạo đầu**. Không có frame queue 0/5 để thu hoặc giả định. March đầu chỉ
được xác minh khi frame mới đọc được 1/5; bốn đạo sau cần lần lượt 2/5, 3/5,
4/5 và 5/5 từ queue có provenance. `before_count=0` trong journal lượt đầu là
thứ tự job, **không phải** số queue đã quan sát. `DISPATCHED` không phải
`VERIFIED`. Đóng FIRST DONE tại 5/5; thời gian đào/về chỉ là ước lượng có
nguồn nếu ghi. Return/refill, buff và chu kỳ 24 giờ thuộc mốc daily farm sau.

Guard tự kiểm mỗi lượt là kiểm kỹ thuật, không phải yêu cầu operator duyệt.
Job này không cấp quyền cho hành động tài khoản/mật khẩu, xóa tài khoản, tiêu
gem/item, chuyển tài sản hoặc action ngoài catalog GATHER. Model local là cấu
hình động và chỉ chọn trong candidate đã được harness ràng; không phát input
hay sửa cặp game gợi ý. Model ROOT do người dùng chọn trong phiên, đội repo
dùng profile `inherit` và chọn vai/effort theo từng gói, không ghim tên model.

## Nguồn thẩm quyền

| Vấn đề | Nguồn hiện hành |
|---|---|
| Mục đích và ranh giới | [PROJECT_DECLARATION](PROJECT_DECLARATION.md), [GOAL](GOAL.md) |
| Nghiệm thu và yêu cầu | [PRD](PRD.md), [SRS](SRS.md) |
| Quyền job | [SESSION_AUTHORITY](SESSION_AUTHORITY.md) |
| Thứ tự gói | [BUILD_PLAN](BUILD_PLAN.md) |
| Node, edge, blocker kỹ thuật | [engineering graph](../config/engineering_graph.yaml), [protocol](GRAPH_ENGINEERING.md) |
| Mức đã chứng minh | [runtime-status](../runtime-status.yaml), [COMPLETION_AUDIT](COMPLETION_AUDIT.md) |
| Đội và phương pháp | [team](../.codex/team.json), [AGENT_OPERATIONS](AGENT_OPERATIONS.md) |

`ROADMAP_STATUS.md` chỉ điều hướng; B003/R3/G6 là benchmark và endurance lịch
sử, không trở thành cổng duyệt từng March hoặc điều kiện FIRST DONE mới.

## Bằng chứng đã có

[GATHER-EVIDENCE](../workspace/agents/gather-evidence/root/BRIEF.md) đã đối
chiếu repo và artifact offline. [Survey F1-C](../workspace/agents/f1c-evidence/root/HANDOFF.md)
đọc được các ảnh queue 1/5–5/5 độc lập; chuỗi OCR `0/5` cũ là quest panel,
không phải queue. [Recon New Troop](../workspace/agents/first-done-recon/nghien_cuu/HANDOFF.md)
và xác nhận của người vận hành hỗ trợ đường cặp game tự điền → March. Ảnh
5/5 lịch sử có can thiệp, chỉ chứng minh occurrence đó, không chứng minh một
job năm đạo tự chủ. Capture thụ động ngày 2026-09-23 chỉ cho `CITY_VIEW`;
không có input, mission tick hay model call từ lần capture này.

F1 job/guard/client/formation, F2 journal/coordinator/driver, F3 attempt audit
và F4 attestation consumer đã được nối trên đường CLI canonical ở mức
**WIRED offline** theo [runtime-status](../runtime-status.yaml). Gói
`first-march-bootstrap` sửa giả định 0/5 tại cùng các node: attestation schema
v2 ghi queue chưa đo; coordinator tạo marker phi số chỉ từ New Troop mới gắn
job; guard cho lượt đầu theo marker đó; engine, journal và auditor đòi hậu
kiểm 1/5 mới. Lượt 2–5 vẫn dùng baseline queue số có nguồn. Classifier mở
New Troop không còn đòi chữ Queue khi UI chưa xuất hiện. [Handoff attestation](../workspace/agents/first-march-bootstrap/tho_dung/HANDOFF.md),
[test handoff](../workspace/agents/first-march-bootstrap/nguoi_thu/HANDOFF.md)
và [validation ROOT](../workspace/agents/first-march-bootstrap/root/VALIDATION.md)
ghi phạm vi kiểm chứng. Full pytest, engineering graph và NNC team validator
đã PASS offline. Đây không phải live proof.

Plugin `shin-agentic-work@personal` 0.1.0 và NNC đã được đối chiếu trong
[plugin check](../workspace/agents/gather-evidence/root/plugin-check.md).
`.codex/team.json` giữ profile model động; các role TOML được tái sinh từ
manifest hiện hành bằng NNC, không ấn định tên model.

## Gói kế tiếp và điểm chưa chứng minh

Gói kế tiếp là **F4-B job-scoped host preflight trace, offline**. `owned_nodes`:
producer `host_input_isolation_evidence` và consumer preflight của
`gather_job_driver`/`gather_cli`. `upstream_dependencies`: attestation đã
ghim digest, attempt chain F3-B, coordinator và recorder trace hiện có.
`downstream_consumers`: input guard và một occurrence live riêng sau này.
`acceptance_evidence`: mỗi tick có trace mới đúng `run_id` và client đã xác
nhận; thiếu/cũ/sai focus hoặc recorder lỗi thì dừng trước runner.
`known_blockers`: telemetry recorder về input ngoài luồng hiện tự khai, chưa
là phép đo độc lập; chưa có startup attestation game thật hoặc hậu kiểm 1/5
cho job mới. `graph_delta_expected`: trace → preflight driver/tick → guard
hiện hành, không mở input path song song. [Brief F4-B](../workspace/agents/f4b-host-trace/root/BRIEF.md)
là hồ sơ làm việc offline đã bỏ tiền đề 0/5 cũ.

Hai công tắc `--gather-job --arm-live` vẫn chặn. FIRST DONE tổng thể còn
`UNIMPLEMENTED`: chưa có một occurrence game thật tự chủ đi 1/5→5/5 cùng
job/client/nhân vật. Gói hiện tại chỉ offline; game có thể tắt. Lần live sau
cần một phạm vi và preflight riêng, không suy quyền từ test hay tài liệu.
