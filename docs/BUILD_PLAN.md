# Auto_ROK — kế hoạch xây dựng hiện hành

[GOAL](GOAL.md) xác định FIRST DONE; [PRD](PRD.md) xác định nghiệm thu;
[SRS](SRS.md) xác định mệnh đề kỹ thuật; [engineering graph](../config/engineering_graph.yaml)
xác định authority node. Mức đã chứng minh chỉ lấy từ
[runtime-status](../runtime-status.yaml) và [COMPLETION_AUDIT](COMPLETION_AUDIT.md).
Kế hoạch này là thứ tự việc cần làm, không phải quyền chạy live.

## Đường FIRST DONE

Một công việc GATHER cho một nhân vật đã đăng nhập: người vận hành ủy quyền
một lần, harness giữ cặp New Troop do game tự điền rồi bấm March cho từng đạo,
hậu kiểm 1/5 khi UI queue xuất hiện sau đạo đầu, rồi 2/5→3/5→4/5→5/5.
Đạt 5/5 thì đóng vòng; ước lượng
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
offline, không phải live proof. Ở giai đoạn F1, CLI còn chặn
`--gather-job --arm-live`; cổng hiện hành được xử lý tại F6-B.

**F1-C1/C2 đã nối offline:** job lưu HWND/PID/process path từ capture đầu và
kiểm ở các frame tiếp theo lẫn ranh giới input. `gather_fact_extractor` tạo
fact New Troop chỉ từ ảnh có hash khớp, OCR/target cùng frame, hai vùng chân
dung có hình, quân đã chọn và nút March hiện hành. Bốn ảnh New Troop archive
đọc dương; ca thiếu, stale, sai client, nút xám và chân dung trống là test
tổng hợp, không phải quan sát game thật. CLI synthetic dùng MissionRunner và
actuator giả đã tiêu thụ fact và guard; toàn bộ pytest, graph, NNC validator
PASS. Revoke hoặc frame/job hết hạn trong lúc đọc ledger đều chặn trước input.
Đó là `WIRED` offline, chưa chứng minh live. Không gửi input đổi chỉ huy.

**F1-C provenance:** `character_id` của CLI vẫn chỉ là cấu hình.
[F4-A1 attestation](../workspace/agents/f4a-startup-attestation/root/VALIDATION.md)
đã triển khai artifact xác nhận một lần ràng job/frame/client/thời điểm ở mức
offline; [F4-A2](../workspace/agents/f4a-attestation-wiring/root/VALIDATION.md)
đã nối driver/tick tiêu thụ; F6 đã có artifact từ frame thật trước navigation
([occurrence](../workspace/agents/f6-live-gate/root/LIVE_OCCURRENCE.md)). Ảnh âm
New Troop thật chưa có. Reader
queue đã đọc đúng các snapshot 1/5–5/5. Người vận hành xác nhận UI queue bên phải
chỉ xuất hiện sau đạo đầu. Bản chỉnh hợp đồng khởi đầu bỏ yêu cầu 0/5,
ghi queue là chưa đo trước March đầu và đòi hậu kiểm mới 1/5; chuỗi OCR `0/5`
trong quest panel không thể làm baseline. Chưa có hậu kiểm 1/5 từ một job mới
trên game thật. Quyền khởi đầu không cần Windows Hello trong ranh
giới same-user local; nếu threat model đổi thì mở issuer riêng.

## F2 — Nối canonical runner và hậu kiểm năm lượt

**Owned nodes:** `gather_cli`, `mission_engine`, `policy_overlay`,
`post_action_verification`, `mission_store`, `gather_runtime_evidence`.

**Upstream:** F1 và queue/current-frame facts. **Downstream:** FIRST DONE
audit và lần live được ủy quyền sau này.

**Việc:** đi qua đường input guard hiện có, không tạo motor song song. Trước
mỗi march đọc New Troop readiness và quyền từ frame mới; sau dispatch đòi 1/5
ở lượt đầu, rồi tăng đúng một theo số queue đã đọc cho bốn lượt sau,
ghi `DISPATCHED` và `VERIFIED` riêng, khóa retry khi kết quả chưa rõ. Bắt
không giả lập một quan sát số 0 trước đạo đầu; đóng sau năm postcondition
1/5→2/5→3/5→4/5→5/5.

Chia theo dependency: F2-A ghi journal VERIFIED/recovery; F2-B chọn slot và
gọi canonical runner một tick; F2-C điều khiển bounded ticks/occurrences của
cả job từ một lần khởi đầu. Gói preflight sau F2-C phải ràng bằng chứng cô
lập input vào job thay vì buộc người vận hành xác nhận mỗi slot. Các phần này
vẫn offline cho đến khi preflight live có nguồn được kiểm riêng.

**Nghiệm thu:** replay đạo đầu hiện UI 1/5 rồi 2/5→5/5 và failure matrix
(missing frame, queue không
tăng, wrong character, timeout, restart/duplicate); structural wiring test
chứng minh CLI thật dùng fact/guard. Graph PASS. Không kết luận live từ replay.

## F3 — Audit offline và live validation có scope

**Owned nodes:** FIRST DONE acceptance audit, `gather_runtime_evidence`,
`runtime-status` chỉ khi có bằng chứng mới.

**Upstream:** F0–F2. **Downstream:** quyết định release.

**Việc:** audit chỉ nhận năm hậu kiểm mới và quyền công việc khớp, phân biệt
manual intervention với autonomous run, report ước lượng có nguồn. F3-A/B đã
nối auditor với chuỗi attempt của driver ở mức `WIRED` offline
([kiểm chứng](../workspace/agents/f3b-resumable-closeout/root/VALIDATION.md));
chỉ sau F4 preflight và bằng chứng thật, ROOT mới lập một occurrence live có
scope cụ thể. Không dùng approval B003/R3 cũ và không suy quyền từ tài liệu.
Live validation giữ preflight
foreground/current frame/input isolation và stop condition. Một vòng đạt
FIRST DONE ở mức `LIVE_PROVEN_ONCE`; repetition cần occurrences mới, stable
cần cửa sổ vận hành riêng.

**Nghiệm thu:** offline validator phát hiện stale/mismatch/receipt-only và
thiếu 1 trong 5 postconditions; live chỉ được nâng theo artifact thật. Đây
không phải lệnh chạy game ngay.

## F4 — Preflight một lần cho năm lượt

**Owned nodes:** consumer của `startup_character_attestation`, job-scoped
`host_input_isolation_evidence` và đường preflight driver/tick hiện có.

**Upstream:** F3-B đã nhận; F4-A1/F4-A2 đã có nhánh startup chỉnh theo UI thật ở mức offline.
**Downstream:** một occurrence live riêng được ủy quyền sau này.

**Thứ tự:** F4-A2 đã nối một attestation bất biến vào cả driver và tick trực
tiếp ở mức `WIRED` offline. F4-B đã nối recorder thụ động vào driver: trước
mỗi tick còn mở, driver lấy `run_id` từ coordinator, thu trace riêng rồi kiểm
tuổi trace, client attested và focus; CLI kiểm lại trước runner. Test tổng hợp
cho năm trace riêng và các ca sai/thiếu, nên trạng thái vẫn chỉ `WIRED` offline
theo [runtime-status](../runtime-status.yaml). Một xác nhận quiescence và đường
recovery được cấp lúc khởi động drive; không có prompt mỗi march. Không tìm frame 0/5: hậu kiểm đạo đầu cần frame mới 1/5;
không lấy dữ liệu quest panel hoặc fixture tổng hợp làm
baseline. Recorder
host vẫn tự khai zero input ngoài luồng, nên cần nguồn telemetry độc lập trước
khi dùng nó làm bằng chứng không có can thiệp. Hai công tắc
`--arm-live` được giữ chặn trong các gói offline F4; F6-B đánh giá riêng
điều kiện mở cổng qua đường canonical.

F4-C đã khảo sát API Windows ở mức tài liệu, không lắp hook. Low-level hook
có thể mất mà không báo, nên chưa có thiết kế đo liên tục chứng minh được
vắng input; [ROOT review](../workspace/agents/f4c-host-telemetry/root/VALIDATION.md)
giữ giới hạn đó. F5 đã kiểm kê offline từng artifact và cổng của một job thật
([ROOT validation](../workspace/agents/f5-live-readiness/root/VALIDATION.md));
không giả định F4-C đã tháo chốt.

## F6 — Lịch tài nguyên và occurrence FIRST DONE

Người vận hành đã chọn `DEFAULT_FARM` trong [PRD §3.2](PRD.md) cho năm đạo.
F6-A đã nối lịch năm slot bất biến do bộ phân bổ hiện hành sinh ra vào quyền
job, attestation, driver, CLI canonical và audit ở mức **WIRED offline**
([ROOT validation](../workspace/agents/f6-resource-schedule/root/VALIDATION.md)).
Không thể dùng launch spec một `resource_type` cho cả năm lượt để nhận nghiệm
thu này. **Owned nodes:**
`farm_work_process`, `gather_job_authority`, `startup_character_attestation`,
`gather_job_driver`, `gather_cli`. **Upstream:** allocator, compiler, job store.
**Downstream:** runner và audit. **Nghiệm thu:** test mix, sai slot/resource,
resume, digest/attestation, evidence tamper và graph PASS; code được ROOT
review. Mức chứng minh hiện hành đọc từ runtime-status; kết quả gói offline
không tự nâng nghiệm thu live.

F6-B đã nối opt-in `--arm-live` từ driver tới tick job schema v2, vẫn bắt buộc
attestation, trace đúng run/client và mới, foreground/current frame, guard,
quota và hậu kiểm trước khi tiến slot ([ROOT validation](../workspace/agents/f6-live-gate/root/VALIDATION.md)).
Không thêm quyền tài khoản hoặc duyệt từng march. ROOT đã thử job mới trên
nhân vật xác nhận bằng frame/attestation mới: city-to-map navigation qua guard,
Search đã được hậu kiểm bằng frame mới, rồi GOLD và SEARCH được chọn tự động;
detail classification hiện dừng với zero March.

F6-C đã nối vùng OCR Search vào producer canonical và target nguồn riêng;
ROOT kiểm replay thật, 73 focused tests, graph/NNC và pending live hậu kiểm
PASS ([validation](../workspace/agents/f6c-search-regions/root/VALIDATION.md)).
F6-D hiệu chỉnh Resource Point/GATHER trên frame detail thật; reviewer kiểm
world-map coordinate còn hiện sau panel có cạnh tranh classifier không.
Chỉ sau ROOT kiểm mới nối cùng occurrence đang mở; không reset checkpoint
hoặc gửi lại input đã phát. Mỗi claim nâng theo artifact thật. Trace hiện chỉ tự khai zero input;
bằng chứng này không được diễn giải thành phép đo độc lập về mọi can thiệp
của host. F6-D đã qua replay thật, 119 focused test ROOT và một live observation
hậu kiểm detail; không phát lại Search.

F6-E nối phục hồi journal-write vào driver/audit canonical từ [diagnostic](../workspace/agents/f6-driver-flake/nguoi_thu/HANDOFF.md).
Owned: driver/coordinator/verification/audit recovery. Upstream: reservation,
client, proof VERIFIED và failed-write tick bất biến cùng attestation/attempt.
Downstream: journal, audit và eligibility slot tiếp. Nghiệm thu: injection giữa
vòng/lượt năm, receipt gắn proof, recovery không input, ca âm tamper/missing,
ongoing I/O/expiry/revocation vẫn chặn và focused tests/graph PASS. Graph nối
producer proof/tick/ledger tới driver và bound receipt tới audit; không xem
failed append là thành công và không sửa evidence lịch sử. ROOT đã nhận
F6-E với301 tests/23file, graph/NNC và review exact-origin PASS, WIRED offline.

F6-F sửa contract từ Drawer0/5 thật: optional sourced zero không thành numeric
baseline; coordinator/runner/verifier/guard/evidence/audit cùng dùng ordinal
đầu và hậu kiểm1/5. F6-G giữ typed tick error, không trust metadata thiếu hoặc
progress giả. ROOT94 integration và28 guard tests, graph/NNC PASS; review
read-only PASS. Broader run có native I/O denial và lỗi thiếu captured_at đã
sửa; không nhận broad suite PASS. [Validation](../workspace/agents/f6f-optional-zero/root/VALIDATION.md)
đóng hai gói WIRED offline; live năm đạo vẫn là bước nghiệm thu tiếp.

F6-H110 focused tests và replay captured-client handoff, review/graph PASS:
coordinator đọc binding bền sau observation đầu. F6-I111 tests và review/graph
PASS nối refresh ordinal đầu qua resume New Troop; detector formation không
cần sửa. [F6-I validation](../workspace/agents/f6i-navigation-ordinal/root/VALIDATION.md)
ghi exact checkpoint cause và test navigation/pending/March, WIRED offline.
Job05 đã phát March1 một lần và giữ pending: ảnh thật hiện1/5 nhưng reader
chưa biết variant denominator5. F6-J train offline từ native capture/hash thật
bằng trainer canonical, giữ ROI/distance/unknown refusal; nghiệm thu ảnh thật,
archive1..5 và negatives trước frame live mới. Không replay March hoặc mở
slot2 khi chưa VERIFIED1. F6-K nối admission cho đúng một pending March bằng
reservation/checkpoint/original dispatch artifact/attempt chain; driver tái dùng
latest open start nguyên bytes, pending verifier chạy trước selector. ROOT24
focused tests/review/graph/NNC PASS; integrated172 tests có1 native I/O denial,
không nhận broad PASS. Same-job observation-only resume đã hậu kiểm/journal1;
bốn slot tiếp và audit closeout là nghiệm thu còn lại. Các kết quả occurrence
đọc từ runtime-status.

F6-L thuộc producer observation: mỗi capture/OCR/projection đi vào một fresh
exclusive directory, downstream đọc exact image_path. Test phải chứng minh
old artifact không đổi, held old destination không bị replace, publication
failure không trả bundle/advance timestamp, provenance và guards giữ nguyên.
F6-M nối failure-diagnostic contract của F6-G vào attempt audit: terminal
diagnostic của failed report mang zero authority; không được tạo tiến độ hoặc
proof. Latest unchanged open start chỉ reuse sau active authority/full preflight;
exact pending March và advanced COMPLETE recovery giữ contract riêng. Không
retry I/O hoặc xóa failed history để mở đường live. Acceptance records nằm dưới
workspace/agents của từng gói; ROOT chọn bước theo bằng chứng và hạn job thật.

F6-P tiếp tục theo trạng thái game mới; job05 đã hết hạn và UI đạo không còn
hiện nên không ghép proof cũ với vòng mới. Source/schedule/job pins cũ giữ
nguyên. Job06 dùng cùng pipeline và quyền FIRST DONE hiện hành; Search ROI
3x được đo từ native frame thay2x thất bại,37 tests PASS. Auditor nhận đúng
empty callback-exception report với null progress,33 negatives/new +3 original
diagnostic tests PASS. Numeric Drawer baseline được wrapper canonical truyền
sang New Troop post-observation trong cùng tick;99 coordinator/guard/verifier
tests trước khi gom factory; bản cuối13 critical PASS, broader105 có1 native
journal denial; không nới tuổi frame/baseline. F6-Q bỏ cursor khỏi capture,
23 ROOT capture/wiring tests PASS. F6-R/S thêm đúng glyph3/4 từ native manifest,
ROOT54/56 queue/trainer/provider tests PASS. Mức native, closeout và giới hạn
vòng có hỗ trợ được cập nhật tại runtime-status/ROOT; kế hoạch không sở hữu
bản tiến độ thứ hai. F6-O continuation tạm hoãn sau
quota failure, không có module/issuer/receipt đã được nhận.

F6-T là nghiệm thu vòng mới với runtime/profile cố định. F6-U xử lý một
variant New Troop qua ảnh native có provenance: đọc riêng nhãn Units và kiểm
quân game tự điền có slider ít fill, giữ các refusals rỗng/zero/disabled/stale.
Sở hữu windows_ocr_direct/gather_fact_extractor; upstream capture/hash/client
thật, downstream classifier→formation→job guard. Nghiệm thu offline yêu cầu
default acquisition được wiring, exact-frame positive, archived positives và
meaningful negatives, focused tests/graph/review. Sửa giữa vòng chỉ là hỗ trợ;
nghiệm thu tự chủ cần một job mới cố định nguồn. Tiến độ và mức chứng minh
vẫn chỉ ở runtime-status cùng ROOT.

F6-W thay điều kiện Search phụ thuộc nhãn ngoài farm bằng image landmarks của
nút tìm kiếm và biểu tượng tài nguyên, kiểm bố cục/current frame. Sở hữu leaf
perception→classifier/foreground suppression; dùng matcher canonical, giữ
grounding/input authority riêng. Nghiệm thu gồm exact blocked Search không OCR,
farm-category positives và city/modal/stale/hash/layout/ambiguity negatives.
Live dùng job mới, nguồn cố định; không giao agent hoặc duyệt từng nút trong vòng.

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
