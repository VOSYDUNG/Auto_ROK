# Auto_ROK — kế hoạch xây dựng hiện hành

[GOAL](GOAL.md) giữ mục tiêu, [PRD](PRD.md) giữ nghiệm thu,
[SRS](SRS.md) giữ chi tiết và [graph](../config/engineering_graph.yaml) giữ
node/edge. [runtime-status](../runtime-status.yaml) sở hữu mức đã chứng minh.
Kế hoạch chỉ giữ **việc còn lại**, không sao lại lịch sử F0–F6-W hoặc cấp quyền.
Chi tiết gói đã làm ở Git và evidence index trong [ROOT](ROOT.md).

## Phương án chọn sau audit

Sửa canonical driver và chứng minh trọn chu kỳ trước khi tối ưu tốc độ hoặc
mở rộng mission. Dùng chuỗi nghiệp vụ `Mouse_key.Daily_farm.Find_pit` làm đối
chiếu thứ tự, giữ action surface/grounding/guard của harness hiện hành. Không
import/chạy actuator legacy hoặc dựng runtime thứ hai. Ưu thế 2 account × 4
nhân vật là thông tin người vận hành cung cấp; chưa benchmark lại ở đây.

## GATHER-CYCLE-REPAIR — gói coding kế tiếp

**Đầu ra:** một path cùng driver đi từ CITY_VIEW qua Search → loại tài nguyên
→ resource detail → Drawer → New Troop → March → hậu kiểm cho đủ năm slot;
lịch và nghiệm thu lấy từ PRD. Source hiện tại là `main@4ea9567` cộng phần
chuẩn hóa tài liệu, chưa có sửa runtime trong gói audit.

**Owned nodes:** `gather_job_driver`, `gather_cli`, `gather_job_coordinator`,
`gather_runtime_evidence`; chỉ sửa upstream
`mission_runner`/`gather_job_store` khi reproducer chứng minh cần integration.
File dự kiến: `scripts/run_gather_job.py`, `scripts/run_gather_tick.py` nếu cần
signal progress, tests driver/route; journal diagnostic đi cùng consumer.

**Upstream:** scope/attestation/client, mission YAML và profile đã calibration,
current-frame facts, ordered journal và saved job09.
**Downstream:** một occurrence FIRST DONE mới, năm proofs và closeout.
**Known blockers:** idle chỉ nhìn số VERIFIED; route test còn rút gọn; một
broad audit fixture không append đủ journal. Không coi lỗi journal là zero input.
**Graph delta expected:** làm rõ edge navigation progress → driver liveness;
không thêm engine/actuator hoặc lược guard/provenance.

**Acceptance evidence trước live:**

- Reproducer từ job09 làm rõ lỗi; test advancing navigation không tăng VERIFIED
  vẫn đến March. Frame mới, choice, checkpoint revision đơn lẻ chưa đủ làm proof
  tiến triển: dùng chuyển trạng thái/fact/postcondition được canonical runner
  xác minh. Unknown/attempted input không tự được nhận như VERIFIED.
- Composed offline route dùng compiler/runner/coordinator/driver thật và capture/
  actuator substitute; city-start qua đủ bước cho năm loại slot tới 1/5→5/5,
  đúng schedule, game-filled formation giữ nguyên và durable closeout. Phải
  ghi rõ signal nào synthetic/native; không dựng COMPLETE để thay đường cần test.
- Ca stuck, lặp qua lại, reobserve không tiến, expiry/revoke/foreign client bị
  chặn bởi tick/wall bounds có lý do. Không chỉ tăng `max_idle_ticks` hoặc sleep.
- Pending/uncertain March chỉ hậu kiểm, không dispatch lại; quota/journal/proofs
  không ghép job. Journal failure có diagnostic đầy đủ, reservation giữ nguyên,
  exact-proof recovery không input. Có giải thích tái hiện và regression cho
  write failure; không nhận isolated pass làm I/O stability hoặc sửa bằng retry mù.
- Focused/integration/wiring tests, graph và review phù hợp đạt. Assets có trong
  checkout. Không chạy bộ test rộng đồng thời hoặc đổi acceptance để cho xanh.

Model/effort theo lựa chọn người dùng và công cụ của **gói**; context ngắn tự
đủ, autonomy offline. Builder sở hữu path này; reviewer độc lập kiểm guard/
proof/recovery sau khi patch ổn. ROOT ghim nguồn và giữ live consumer.

## Nghiệm thu occurrence mới

Sau gói trên, ROOT dùng quyền đã cấp và fresh startup/job/client/frame theo
SESSION_AUTHORITY, nguồn/profile/assets cố định. Chạy cả job trong một driver,
không hỏi quyền hoặc brief từng March. Dừng khi focus/scope/input uncertainty
hoặc quota/proof lỗi. Không chỉnh code/profile giữa vòng đang nhận tự chủ.

Năm proofs mới có 1/5→5/5, cùng job/client/schedule/formation và closeout hợp
lệ mới nhận LIVE_PROVEN_ONCE. Vòng có hỗ trợ được ghi riêng. Giới hạn telemetry
host vẫn phải nói đúng mức đo. Chưa có evidence thì không hứa thời gian trọn vòng.

## Sau vòng trọn: đo và tối ưu, rồi mở rộng

Một benchmark cùng boundary tách thời gian capture/host check/OCR/setup/dispatch/
verify. Nếu process/provider reconstruction chiếm đáng kể, thử **một process
sống suốt job** bằng canonical factory hiện hành, giữ fresh observation trước/
sau hành động và guards; so baseline trên cùng route. Chỉ thay asset/OCR strategy
khi corpus chỉ ra loại lỗi, ưu tiên control lớn/template/bố cục cho panel ổn định.
Không xem optimization này là lý do tiếp tục hoãn sửa liveness đơn giản.

Sau FIRST DONE: return/home → refill → buff → chu kỳ hằng ngày; sau đó mới xoay
nhiều nhân vật/tài khoản và đo scale theo đầu vào. Market/delivery, PVE, rally,
endurance G6 và benchmark model là nhánh riêng, không chặn FIRST DONE. Local
LLM chỉ chọn ở bất định thật, không được giao click/raw coordinates.
