# Tuyên bố dự án Auto_ROK

Ngày ban hành: 2026-09-19 · Trạng thái: **hiệu lực** · Thay thế mọi tuyên bố mâu thuẫn trước đó

Đây là tài liệu cao nhất của dự án. Khi bất kỳ tài liệu, đoạn code hay bằng chứng nào
mâu thuẫn với tài liệu này, tài liệu này thắng và cái kia phải được sửa hoặc đưa vào
`docs/archive/`.

---

## 1. Dự án này là cái gì

**Auto_ROK là một mô hình ngôn ngữ chạy cục bộ, vận hành một client Rise of Kingdoms
đang hiển thị trên đúng một máy Windows, thông qua một harness xác định.**

Câu trên có một chủ ngữ duy nhất: **LLM local**. Harness không phải sản phẩm — harness
là nền móng để LLM đủ điều kiện quyết định. Mọi quyết định thiết kế phải trả lời được
câu hỏi: *điều này làm LLM quyết định nhanh hơn, đúng hơn, hay ít nhiễu hơn ở chỗ nào?*

Trước ngày ban hành, dự án tự gọi mình bằng bốn cái tên khác nhau trong bốn tài liệu
("harness", "build protocol", "branch tiến hoá từ PoC", "Agentic OS"). Từ nay chỉ còn
một tên và một chủ ngữ như trên.

### Tỉ lệ trách nhiệm 80/20

| Bên | Tỉ trọng | Sở hữu |
|---|---|---|
| Harness | 80% | Thu hình, OCR, dựng trạng thái, lọc ứng viên, nối đất mục tiêu, cô lập input, actuation có chốt chặn, phê duyệt, checkpoint, xác minh hậu điều kiện, bằng chứng bất biến |
| LLM local | 20% | Chọn đúng một `ActionChoice` đã được harness lọc sẵn, hoặc trả `NEEDS_DECISION`, hoặc báo *game đã thay đổi, cần huấn luyện lại* |

LLM **không** được: nhìn toạ độ thô, đọc bộ nhớ tiến trình, giữ đồng hồ, quyết định lịch,
tiêu tài nguyên, hay phát input. Nếu một ngày LLM cần một trong các quyền đó, đó là dấu
hiệu harness còn thiếu sâu, không phải lý do nới quyền cho LLM.

### "Luôn bật" không có nghĩa là "luôn có việc"

LLM local chạy thường trực như một người quan sát rảnh rỗi. Harness chỉ gửi cho nó một
gói ngữ cảnh có giới hạn khi phát sinh tín hiệu `NEEDS_DECISION` hoặc `UNKNOWN_STATE`
thật. Không có tín hiệu thì nó ngồi im. Đây là điều khoản hợp đồng, không phải tối ưu
hiệu năng.

---

## 2. Ba trụ

Dự án được tổ chức theo ba trụ, không theo tầng kỹ thuật.

**Trụ 1 — Harness (80%).** Phần xác định, không suy đoán: thu hình CPU-only, OCR, phân
loại trạng thái, biên dịch mission, lọc ứng viên, actuation có chốt, xác minh, bằng chứng.

**Trụ 2 — LLM local (20%).** Biên quyết định có ràng buộc: chọn một ứng viên có sẵn,
từ chối khi bằng chứng không đủ, và phát tín hiệu game đã đổi.

**Trụ 3 — Kiến thức gameplay.** Luật chơi, nhịp game, dữ liệu tài khoản. Đây là trụ
quyết định LLM *hiểu* game tới đâu. Trước ngày ban hành, trụ này bị xé làm ba nơi
(`knowledge/`, `config/`, `harness/mission_timeline.py`) và không nơi nào làm chủ. Từ nay
`knowledge/` là nơi duy nhất chứa kiến thức game đã quan sát, mỗi mẩu kèm nguồn và ngày.

---

## 3. Nhịp mission — đo, không hardcode

Nguyên tắc: **nhịp của mission phải suy ra từ số đo lưu trong cơ sở dữ liệu, không phải
từ hằng số thời gian viết cứng trong code.**

Đường cũ (`Mouse_key.py`, lớp `Daily_farm`) mã hoá vòng farm bằng toạ độ cứng cộng
`time.sleep(1)`. Nó không thể suy luận về năng suất, vì nó không đo gì cả. Đó là thứ
phải bỏ, không phải thứ để tối ưu.

Các đại lượng bắt buộc phải đo và lưu, không được viết cứng:

- thời gian quân đi tới mỏ;
- thời gian đào hết mỏ (game có hiển thị trong bảng Troops);
- **thời gian quân về** — game không hiển thị, bảng cũ bỏ sót hoàn toàn, nhưng nó chiếm
  chỗ trong hàng đợi y như hai đại lượng kia;
- thời gian slot hàng đợi bị bỏ trống giữa hai lượt gửi (đây là thước đo *gãy nhịp*);
- thời gian còn lại của buff tăng tốc thu thập.

Hằng số do game quy định — mốc reset `00:00 UTC` (tức `07:00` giờ Việt Nam), cooldown
đóng góp liên minh 30 phút, tối đa 20 lượt mỗi chu kỳ reset — vẫn là hằng số và được
khai báo trong `config/mission_layer.yaml`. Ranh giới là: **luật game thì khai báo, hành
vi quan sát được thì đo.**

### Mục tiêu năng suất

Giữ **mọi slot hàng đợi có quân** và **buff tăng tốc thu thập không bao giờ về 0**, liên
tục 24/24. Hai đòn bẩy độc lập, cùng đo được, cùng có thể gãy nhịp độc lập.

---

## 4. Phát hiện game đã thay đổi

LLM local có đúng một nhiệm vụ không bị ràng buộc cứng: nhận ra game đã đổi.

Giống người chơi thật — thứ xưa nay vẫn làm được nay không làm được nữa, hoặc một màn
hình biến mất một thời gian — thì phải báo. Khi đó LLM phát `retraining_required` và
**không được đoán mục tiêu thay thế**. Harness dừng, chờ huấn luyện lại.

---

## 5. Ranh giới

**Trong phạm vi:** một máy Windows thật, một tài khoản đã đăng nhập, một client ROK đang
hiển thị; thu hình và xử lý chỉ bằng CPU/RAM; chỉ tương tác qua đúng bề mặt nhìn-và-bấm
mà người chơi có.

**Ngoài phạm vi:**
- Docker, máy ảo, Hyper-V, mọi đường chạy phụ thuộc GPU;
- đọc bộ nhớ tiến trình, chèn code vào game;
- tác tử desktop tự do không giới hạn;
- nghiệm thu chỉ dựa trên việc gọi được model, hay có biên nhận gửi lệnh, hay một tỉ lệ
  OCR chung chung;
- tái sử dụng một phê duyệt hay một bản replay cũ cho một occurrence khác.

Hệ quả bắt buộc: code thuộc đường guest/VM còn sót lại trong repo là **nợ phải xoá**,
không phải tính năng đang tạm nghỉ.

---

## 6. Ba quy tắc chống nhiễu

Ba quy tắc dưới đây sinh ra từ bản audit ngày 2026-09-19, để chặn đúng ba cách dự án đã
tự làm mình mơ hồ.

### 6.1 Một hệ đánh số nghiệm thu duy nhất: **G1–G6**

Trước đó tồn tại song song năm hệ: gate 1–8 (GOAL), R1a/R1b/R2/R3/R4 (PRD), M0–M5
(ARCHITECTURE), P0–P6 (PRD), G1–G6 (script audit). Từ nay chỉ dùng **G1–G6**, định nghĩa
trong `docs/GOAL.md` và thực thi bằng `scripts/audit_goal_readiness.py`. Mọi hệ khác là
lịch sử.

### 6.2 Một nguồn sự thật duy nhất cho trạng thái

Trạng thái dự án **được tính**, không được viết tay. Nguồn duy nhất là kết quả của
`scripts/audit_goal_readiness.py`, đọc từ bằng chứng thật trong `workspace/evidence/`.

`config/engineering_graph.yaml` chỉ còn giữ **cấu trúc kỹ thuật** — ai sở hữu trách nhiệm
gì, cạnh nối ra sao, blocker nào đang mở. Nó **không** còn là nơi tuyên bố mức độ hoàn
thành. `docs/COVERAGE.md` là bản chụp có ngày của kết quả tính toán, không phải bảng
viết tay song song.

### 6.3 Một entrypoint duy nhất

`scripts/run_gather_tick.py` là entrypoint thật và duy nhất cho một tick GATHER. Ba tài
liệu từng tuyên bố `scripts/run_autorok.py` là canonical, trong khi file đó chỉ là 20
dòng re-export, không có trong đồ thị kỹ thuật và không được CI gọi bao giờ.

---

## 7. Quy tắc ngôn ngữ

Trước đó tiếng Việt và tiếng Anh trộn lẫn không theo luật nào. Từ nay:

- **Tiếng Việt** — tài liệu quyết định mà người vận hành đọc và ký: tuyên bố dự án,
  GOAL, PRD, độ phủ, kiến thức gameplay.
- **Tiếng Anh** — mọi thứ gắn trực tiếp với code: docstring, tên biến, thông điệp commit,
  đặc tả kỹ thuật của module, schema.

Tên file luôn tiếng Anh để công cụ không vỡ.

---

## 8. Những gì chưa xác minh

Dự án chấp nhận mang theo các mục `UNVERIFIED`, với một điều kiện: chúng phải được ghi
rõ là chưa xác minh, không được im lặng biến thành giả định.

Các mục chưa xác minh hiện tại được liệt kê trong `docs/COVERAGE.md`. Chúng sẽ được
huấn luyện dần bằng kiểm nghiệm thực địa theo thời gian. Một mục `UNVERIFIED` **không**
chặn việc xây dựng, nhưng **có** chặn việc tuyên bố đã nghiệm thu.

---

## 9. Tài liệu có hiệu lực

| Tài liệu | Vai trò |
|---|---|
| `docs/PROJECT_DECLARATION.md` | tài liệu này — cao nhất |
| `docs/GOAL.md` | mục tiêu và định nghĩa hoàn thành G1–G6 |
| `docs/PRD.md` | yêu cầu sản phẩm |
| `docs/COVERAGE.md` | độ phủ hiện tại, tính từ bằng chứng |
| `knowledge/*.yaml` | kiến thức gameplay đã quan sát, có nguồn và ngày |
| `config/engineering_graph.yaml` | cấu trúc kỹ thuật và blocker đang mở |

Mọi tài liệu khác trong `docs/` là đặc tả module, báo cáo đo đạc, hoặc lịch sử. Không
tài liệu nào trong số đó được phép định nghĩa lại phạm vi dự án.
