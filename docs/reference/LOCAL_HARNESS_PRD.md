# PRD G002 — ROK Windows / Local Computer Use + OCR

Ngày 2026-09-13. Trạng thái: đặc tả và triển khai R1; chưa nghiệm thu Computer Use. Nguồn: yêu cầu trực tiếp, [GOAL](GOAL.md), Auto_ROK HEAD 27fb52b573ceaf88e2f03b43ace6625dc8e465b1. Người dùng nghiệm thu; root quản đốc; chia_lo biên soạn đề, tho_dung xây, kiem_luat kiểm độc lập.

## Vấn đề và luồng người dùng

**Steering tools-first / G003:** phát triển dựa trên game đã mở trên host. Tách runtime xác định (capture/anchor/tool/mission clock/checkpoint/verify) khỏi decision provider (LLM/user). API mission.tick phải hoạt động khi model8080 tắt, nhưng không tự bịa quyết định hoặc thành công. VM không là prerequisite của passive capture/anchor. Action backend vẫn phải chứng minh không chiếm chuột/phím; không suy quyền gửi input từ việc người dùng đã mở game.

Mỗi tool phải có input/output schema, provenance của frame/anchor, pre/postcondition, timeout và lỗi phân loại. Anchor OCR/template/geometry phải gắn target, kích thước/DPI, thời gian/hash ảnh, ứng viên bbox, ambiguity và calibration evidence. Bỏ tọa độ desktop cố định khỏi executable path. Không dùng một tọa độ “tương đối” hardcode mới để giả làm anchor đã nhận diện.

Nhịp mission: due → observe → resolve anchors → check preconditions → plan/decision-needed → dispatch nếu backend được cấp → fresh-observe → verify → checkpoint/next_due. Cancel/retry/backoff/expiry giữ trong state. Dry-run không tăng số completed hoặc ghi hành động đã xảy ra. Không có LLM thì mission cần suy luận được treo có lý do, scheduler vẫn giữ lịch. Chưa tự bật lịch chạy nền từ yêu cầu kiến trúc.

Auto_ROK hiện có gather/thu clan/đổi nhân vật, OCR và dấu xanh; nhưng dùng input host, tọa độ tuyệt đối và sleep cố định. Người dùng muốn local model làm gói việc có kết quả, giữ quota Codex/Claude cho dự án gấp.

Người dùng nhập “Xem nhân vật hiện tại và đề xuất việc farm”, chọn target/ảnh. Hệ thống trả điều nhìn thấy kèm vùng ảnh, điều chưa chắc và phương án. Sau khi guest/workflow đạt gate, người dùng giao gói thu tài nguyên; local tự quan sát–hành động–xác nhận trong guest, dừng khi lệch phạm vi. Có hỏi trạng thái, giải thích, pause/cancel/resume. CLI là giao diện đầu; chat localhost có ảnh và lịch sử là bước tiếp theo.

## Yêu cầu chức năng và nghiệm thu

| ID | Yêu cầu | Bằng chứng |
|---|---|---|
| F01 | Task có intent, target/guest ID, allowed workflows/actions, expiry và ngân sách | Không đủ binding/quyền/ảnh mới thì không dispatch |
| F02 | PNG/JPEG thật hoặc ảnh guest; hash, kích thước, thời điểm capture nếu biết và thời điểm nhập riêng | Ảnh vừa nhập không tự thành ảnh live; timestamp không rõ ghi null |
| F03 | OCR text/bbox; vision riêng cho icon/dấu xanh/mỏ/đội quân | Confidence không có ghi null; không suy icon từ chữ đơn thuần |
| F04 | Scene có object ID, tọa độ theo frame, target, chứng cứ và điều chưa biết | Resize/target change/stale frame làm proposal hết hiệu lực |
| F05 | Local nhận task + scene + lịch sử nén; trả giải thích, intent, expected observation | Schema sai chỉ sửa bounded hoặc hỏi, không chạy text tự do |
| F06 | Computer Use chỉ trong Windows guest được kiểm chứng | Runtime evidence zero host input/focus stealing; không fallback host |
| F07 | Chụp lại, kiểm expected state, action ledger và checkpoint | Không double-action khi resume; trạng thái mơ hồ thì dừng |
| F08 | Hội thoại trạng thái, pause/cancel/resume | Cancel không xếp action mới; resume phải quan sát lại |
| F09 | Session/task/tool/model trace và metrics có version | Missing token/chi phí null; đo cả lỗi/sửa/chuyển tầng |
| F10 | Model registry động và rollback allocation | Model mới chưa canary không tự nhận quyền mới |

## Kiến trúc và DSH lite

CLI/chat → task contract → capture/image → OCR + vision → scene → local model → typed intent → policy → guest action → fresh observation → verifier → report/checkpoint.

Nguồn DSH đã tải và chốt revision. Giữ plugin/model/tool boundary, session transcript và loop bounded. Bỏ khỏi lite đầu: marketplace, shell tùy ý, MCP diện rộng, web của candidate, cloud mặc định, recursive subagent. Không cần build toàn monorepo. Cơ chế port phải có source-path mapping; không dùng SDK thật thì không ghi “đã chạy upstream DSH”. Lite/full DSH dùng runner ID riêng, không gộp điểm benchmark.

GPT-OSS text reasoning nhận OCR/vision; chưa xác nhận khả năng ảnh trực tiếp. Bộ ảnh phải có màn hình ít chữ/nhiều icon, popup/loading và nhiều độ phân giải. Nội dung ảnh là dữ liệu, không sửa policy hoặc yêu cầu chạy shell.

## Windows guest và không chiếm input

Người dùng chọn giữ Windows ROK; chưa chọn hypervisor. Phải xác minh render game, capture khi host làm việc, input trong guest và tài nguyên khi inference chạy. Không mặc định session còn render khi disconnect hoặc PostMessage/cửa sổ ẩn điều khiển được game.

Máy: Windows10 Pro, VT/SLAT, 64 GiB RAM, R5 430 2 GiB, hypervisor chưa hoạt động. Theo [Microsoft](https://learn.microsoft.com/en-us/troubleshoot/windows-server/virtualization/troubleshoot-hyper-v-gpu-assignment-partitioning-passthrough-issues), DDA/GPU-P không được hỗ trợ trên Windows10/11 Pro; không lấy GPU passthrough làm giả định. Chưa có guest thì action path báo chưa khả dụng. Observer hữu ích nhưng chưa hoàn thành bậc 1.

## Gate đề xuất — không phải kết quả hiện có

- **R1a:** OCR thật có bbox/hash/provenance; tối thiểu 20 ảnh ROK gán nhãn, tách 5 ảnh holdout theo nhóm trạng thái, báo CER/WER và precision/recall field. Critical-field precision ≥95%, recall ≥90%; khóa nhãn trước chạy. Mẫu nhỏ chỉ screening.
- **R1b:** 10 câu hỏi trên ảnh thật, ≥9/10 đề xuất được reviewer chấp nhận; không bịa target/coords/icon. Ghi retry/timeout/token; fixture synthetic không tính là bài ROK thật.
- **R2:** 30 phút guest chạy khi host dùng ứng dụng khác; zero host input từ agent/focus stealing, target/frame binding đúng; thử disconnect/resize/cancel. Có runtime trace, không chỉ grep thư viện.
- **R3:** ban đầu 10 lượt một workflow trên một nhân vật, ≥9 hoàn thành với pre/post evidence và zero out-of-scope. Mở rộng bậc 1: 30 scenario đăng ký trước gồm clan/gather/đổi nhân vật, ≥27 hoàn thành, 30/30 có trace; đổi nhân vật chỉ sau quyền cụ thể.
- **Recovery:** 10 cancel + 10 restart, không action mới sau cancel hoặc lặp action khi resume; fresh capture trước tiếp tục. 100% case stale/ambiguous-icon bị chặn, không blind retry.
- **R4:** sau R3 chạy 1 giờ, rồi mới thử 15 giờ. Báo success/hour, intervention, contention, thời gian và chi phí thực; so baseline cùng acceptance trước tuyên bố tiết kiệm.

## Ngân sách và nhân sự

Local một slot, tối đa hai lần sửa có chẩn đoán; deadline/output/context cấu hình theo package. Routine OCR/state/rules dùng script; local suy luận cả gói; cloud compiler/reviewer theo lô, không mỗi frame. Không paid API fallback khi timeout. Mỗi allocation lưu MODEL×EFFORT×CONTEXT×AUTONOMY cùng quyền, lý do và hạn dùng trong G002-HANDOFF; ghế không pin model.

Metrics: requested/effective model/effort, nguồn/cỡ context, input/cached/output/reasoning tokens, tool calls, queue/OCR/model/tool/verify/repair/wall seconds, reviewer minutes, result/failure class. Cached/reasoning không cộng đôi. Delta quota chung tài khoản không quy hết cho ROK; tiền điện = kWh đo × giá thực, thiếu là null. Rate cũ là lịch sử, không phải báo giá hiện tại.

## Gói việc tiếp nối

| Gói | Thực thi | Phụ thuộc | Đầu ra |
|---|---|---|---|
| P0 | chia_lo → root tích hợp | nguồn/yêu cầu | GOAL + PRD + report |
| P1 | tho_dung | P0 | CLI image/OCR/scene/intent/metrics + focused tests |
| P2 | tho_dung; root ghi nguồn | upstream đã tải | Retention matrix: đã port / SDK thật / dự kiến |
| P3 | tho_dung → kiem_luat | P1/P2, model available | Live local observation run; một slot |
| P4 | do_duong → tho_dung | Windows guest choice | Feasibility → cấu hình guest reviewable → action bridge; R2 |
| P5 | tho_dung → kiem_luat | R1/R2 | Gather/clan + verifier/resume; R3 |
| P6 | tho_dung → kiem_luat/root | R3 | Chạy dài + economics + promotion; R4 |

PRD → Plan → Design brief/SRS/Job story → Spec → User story → production package phải bám P1–P6 và acceptance cụ thể. Không mở tất cả ghế cùng lúc.

## Điểm còn mở

Token snapshot của root được trích chỉ từ counter (không xuất nội dung chat): workspace/evidence/g002-root-token-snapshot.json, timestamp2026-09-13T07:41:55Z. Lũy kế toàn session gồm G001/M1/G002: input19,036,984 trong đó cached18,398,848; output112,263 trong đó reasoning16,627. Đây KHÔNG phải token riêng G002, không phải context đồng thời và không quy thành tiền/quota. Nó cho thấy cần kiểm cả repeated context/cache chứ không kết luận mọi usage do thinking. Chưa có counter tách gói/agent thì số đo đó vẫn null.

Ảnh ROK gán nhãn, guest image/license, hypervisor/render benchmark và live workflow acceptance còn thiếu. Cài hypervisor/reboot cần phương án cụ thể để người dùng duyệt trước thay đổi máy. Không host Astra/mua hardware. Robotics/model training/global keyboard logging và tự đổi tài khoản/mua vật phẩm không thuộc đợt đầu. Legacy source không được import để thử nhanh.
