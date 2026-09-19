# PRD — Auto_ROK

Ngày: 2026-09-19 · Phiên bản 1 · Chịu sự điều chỉnh của [`docs/PROJECT_DECLARATION.md`](PROJECT_DECLARATION.md)

Tài liệu này thay thế `docs/reference/LOCAL_HARNESS_PRD.md` (ngày 2026-09-13). Bản cũ
được giữ trong `docs/archive/` làm lịch sử; các hệ đánh số R1a/R1b/R2/R3/R4 và P0–P6 của
nó **không còn hiệu lực**, đã quy về G1–G6.

---

## 1. Bài toán

Người vận hành muốn một client Rise of Kingdoms duy trì năng suất thu thập tối đa liên
tục 24/24 mà không phải ngồi canh, và muốn phần *quyết định* nằm ở một mô hình chạy cục
bộ chứ không phải ở một chuỗi toạ độ viết cứng.

Đường cũ (`Mouse_key.py`) đã chứng minh cách làm sai: toạ độ cứng, `time.sleep`, không đo,
không xác minh. Nó không thể tự biết mình đúng hay sai, nên không thể giao cho nó chạy
không người trông.

## 2. Người dùng

Một người vận hành duy nhất, sở hữu máy và tài khoản, ngồi cùng máy với game. Người này
phê duyệt các hành động rủi ro, cung cấp kiến thức game, và là người duy nhất được quyền
uỷ quyền chạy endurance.

## 3. Phạm vi (Scope)

### 3.1 Luận đề đang kiểm

> **Năng lực = model × giàn giáo.** Trong một miền có ranh giới, giàn giáo thay thế được cho
> dung lượng model.

Phát biểu để có thể sai:

> Với cùng một model ~20B chạy CPU, harness đưa hiệu suất vận hành từ *không chạy nổi* lên
> *trong khoảng X% mốc người chơi giỏi*, trong khi model vào cuộc dưới N lần / 100 tick.

Đo bằng **hai nhánh**, ghi trong `config/harness_benchmark_matrix.json`:

| Nhánh | Là gì | Trạng thái |
|---|---|---|
| Trần | người vận hành tự chơi | **đã có số**: 2h00–2h30 (farm nhà 25 cấp mạnh) · 3h30–4h00 (farm thấp hơn), buff 50% chạy |
| H1 | model yếu + harness đầy đủ | cần đo |

**Không đo nhánh sàn.** Model yếu không harness chắc chắn không vận hành được — đo chỉ tốn
thời gian, không thêm thông tin. Quyết định của người vận hành, 2026-09-19.

**Trần không cần model cloud**, vì tiền đề sản phẩm là chỉ tương tác qua bề mặt nhìn-và-bấm
mà người chơi có. Người chơi giỏi chính là trần.

### 3.2 Trong phạm vi

| Hạng mục | Nội dung |
|---|---|
| Miền | Rise of Kingdoms, **một máy Windows thật**, một client hiển thị |
| Đội hình | nhiều tài khoản × nhiều nhân vật × 5 đạo quân; hiện 2×4×5, **số lượng là đầu vào lúc chạy** |
| Xoay vòng | đổi nhân vật trong game (Settings → Character), **không cần thông tin đăng nhập** |
| Mission | `ACCUMULATE` theo hạn mức + thời hạn; `DEFAULT_FARM` tỉ lệ 1:1:1:2; `DAILY_CITIZEN` |
| Suy giảm | thang 5 bậc, `SCARCITY_FILL` khi khan mỏ |
| Giao hàng | **trong phạm vi nhưng đang KHOÁ** — chờ quan sát bảng cấp Chợ, đường giao, và số thuế |
| LLM | bộ chọn có ràng buộc ở hai tầng; chiến lược (phút) và chiến thuật (giây) |
| Tri thức | `knowledge/*.yaml`, mỗi mẩu có nguồn và ngày |
| Bằng chứng | bất biến, gắn occurrence, G1–G6 |

### 3.3 Ngoài phạm vi, và vì sao

| Ngoài phạm vi | Vì sao |
|---|---|
| Docker, máy ảo, Hyper-V, GPU | ranh giới sản phẩm; **cưỡng chế bằng `tests/test_no_virtualization.py`** |
| Dịch vụ CI | chạy trên máy ảo thuê; thay bằng `scripts/check_local.py` |
| Đọc bộ nhớ tiến trình, chèn code | chỉ dùng bề mặt của người chơi |
| Tác tử desktop tự do | model không bao giờ thấy toạ độ hay bề mặt điều khiển mở |
| Đăng xuất / đăng nhập tài khoản | đổi nhân vật trong game đủ cho quy mô hiện tại; thông tin đăng nhập là hạng mục riêng, có rủi ro riêng |
| Mua vật phẩm bằng gem | hành động tiêu tiền, không hoàn tác; thuộc quyền người vận hành |
| Rally quân, điều phối sự kiện, đổi vương quốc | chưa có hợp đồng quan sát/chính sách/xác minh riêng |
| Nhánh alliance `CLAIM_ALLIANCE_TERRITORY_RSS` | đang `partial`, chặn bởi `A001`; **GATHER chưa đóng thì chưa mở nhánh hai** |
| Nhiều máy, điều phối từ xa | một agent, một máy |
| Model cloud, kể cả để đo | trần là người chơi, không cần cloud |

### 3.4 Điều kiện đóng phạm vi này

Phạm vi coi là hoàn thành khi **đồng thời**:

1. **G1–G6 đạt** — trong đó G6 cần chữ ký uỷ quyền của người vận hành, không phải code;
2. **Hàng đợi đội hình lên 5/5** và giữ được, buff không về 0;
3. **H1 đo được và so được với trần** trên bốn thước: giờ chạy tự chủ · % hàng đợi đầy và
   buff ≠ 0 · lần LLM vào cuộc / 100 tick · lần tự phát hiện game đổi;
4. **`ACCUMULATE` chạy trọn một chu kỳ order**, kể cả khi gặp khan mỏ và tụt bậc.

Giao hàng **không** nằm trong điều kiện đóng, vì nó đang khoá.

### 3.5 Giả định

Sai giả định nào thì phải mở lại phạm vi, không phải vá.

| Giả định | Nếu sai thì sao |
|---|---|
| Buff 50% luôn bật được | mọi mốc chu kỳ sai; lịch xoay vòng phải tính lại |
| Đổi nhân vật trong game là đủ | phải làm đăng nhập tài khoản → hạng mục và rủi ro mới |
| Màn chi tiết tài nguyên loại trừ item tồn tại | không đo được tiến độ hạn mức chính xác |
| Client giữ nguyên độ phân giải và bố cục | mọi ROI và nối đất phải huấn luyện lại |
| Người vận hành có mặt cho các pass quan sát | P3 đứng, kéo theo P4 |

### 3.6 Cái gì buộc mở lại phạm vi

- Game cập nhật đổi bố cục UI → `retraining_required`, dừng, huấn luyện lại
- Số tài khoản vượt quá mức xoay vòng đơn giản chịu được → cần tầng điều phối
- Người vận hành yêu cầu giao hàng tự động **trước khi** quan sát xong bảng cấp Chợ →
  từ chối, vì đó là hành động chuyển tài sản không hoàn tác

---

## 4. Nguyên tắc sản phẩm

1. **LLM là chủ ngữ, harness là nền.** Mỗi tính năng phải nói được nó làm LLM quyết định
   tốt hơn ở đâu.
2. **Xác định trước, suy luận sau.** Việc gì tính được thì harness tính; chỉ đưa lên LLM
   phần thật sự mơ hồ.
3. **Gửi lệnh không phải là thành công.** Chỉ hậu điều kiện nhìn thấy được trên khung hình
   tươi mới tính.
4. **Fail-closed.** Bằng chứng cũ, thiếu hay mâu thuẫn thì dừng, không đoán.
5. **Đo, đừng hardcode.** Nhịp mission suy ra từ số đo đã lưu.
6. **Chỉ qua bề mặt của người chơi.** Nhìn màn hình, bấm chuột phím. Không đọc bộ nhớ,
   không chèn code.

---

## 5. Yêu cầu chức năng

### F01 — Thu hình thụ động
Thu hình client ROK đang hiển thị, chỉ bằng CPU/RAM, gắn HWND, kèm metadata khung hình
(thời điểm, kích thước, hash). Không thu khi cửa sổ đích không ở foreground.

### F02 — OCR và ngữ nghĩa
Chuyển khung hình thành các hộp từ, rồi lắp thành cụm từ có nghĩa và nối đất tới các mục
tiêu chính xác đã khai báo. Đường OCR chính thức là `Windows.Media.Ocr`.

**Yêu cầu hiệu năng (mới, chưa đạt):** một khung hình phải hoàn tất dưới **400 ms**.
Hiện trạng đo ngày 2026-09-19 là **4.525 ms** — xem `docs/COVERAGE.md` §4.

### F03 — Phân loại trạng thái
Từ bằng chứng khung hình, phân loại tất định trạng thái UI trong từ vựng đã khai báo.
Thiếu bằng chứng hoặc bằng chứng cạnh tranh nhau thì trả `UNKNOWN_STATE` /
`AMBIGUOUS_STATE`, không đoán.

### F04 — Đồ thị mission và lọc ứng viên
Biên dịch luồng mission đã huấn luyện thành đồ thị runtime, và với mỗi trạng thái, sinh
ra tập hành động hợp lệ đã lọc. Đây là tập mà LLM được phép chọn trong đó.

### F05 — Biên quyết định LLM local
Gửi gói ngữ cảnh tối thiểu khi và chỉ khi có `NEEDS_DECISION`/`UNKNOWN_STATE`. Nhận về
một ứng viên có sẵn, hoặc `NEEDS_DECISION`, hoặc `retraining_required`. Mọi phản hồi
không khớp ứng viên có sẵn đều bị từ chối.

### F06 — Actuation có chốt chặn
Phát chuột/phím qua Win32 chỉ khi: cửa sổ đích đúng, foreground ổn định, khung hình còn
tươi, phê duyệt của occurrence hiện tại có mặt. Bất kỳ điều kiện nào hỏng thì không phát.

### F07 — Xác minh hậu điều kiện
Sau hành động, thu khung hình mới và chứng minh hậu điều kiện đã khai báo. Với GATHER,
hậu điều kiện là `Queue used` tăng đúng 1.

### F08 — Bằng chứng bất biến
Mỗi occurrence ghi bằng chứng append-only, gắn danh tính (mission/task/run/character).
Trùng đường dẫn thì fail-closed.

### F09 — Dòng thời gian mission theo dữ liệu
Mô hình hoá mốc reset `00:00 UTC` (= `07:00` giờ Việt Nam), nhiệm vụ VIP, cửa sổ Courier
Station, chu kỳ quay vòng của hàng đợi farm, và cooldown đóng góp liên minh 30 phút với
tối đa 20 lượt mỗi reset.

### F10 — Kho đo nhịp
Lưu bền các số đo nhịp và suy ra lịch từ chúng: thời gian quân đi, thời gian đào, **thời
gian quân về**, thời gian slot trống, thời gian còn lại của buff. Lịch **không** được lấy
từ hằng số viết cứng trong code.

### F11 — Liên tục hoá năng suất *(mới)*
Giữ hàng đợi đầy và buff tăng tốc thu thập luôn khác 0.
- Buff `8-Hour Enhanced Gathering`: +50%, 8 giờ, **thời lượng cộng dồn** khi dùng thêm.
- Ba item phủ đủ 24 giờ.
- Đường thao tác: mở Items → tab `BOOSTS` → chọn item → đọc khung chi tiết → `USE` →
  xác nhận.
- **Chốt an toàn:** hộp thoại xác nhận có `YES` **màu đỏ bên trái** và `NO` **màu xanh
  bên phải** — ngược quy ước thường gặp. Nối đất bắt buộc theo nhãn chữ, cấm theo màu
  hoặc vị trí.

### F12 — Phát hiện game thay đổi *(mới)*
Khi một control, nhãn, hay hình dạng hộp thoại đã huấn luyện không còn khớp khung hình
hiện tại, phát `retraining_required` và dừng. Cấm thay thế bằng mục tiêu phỏng đoán.

Mở rộng: LLM được phép **đề xuất** một `ObservedFact` mô tả bố cục mới, kèm bằng chứng khung
hình. Người vận hành duyệt thì nó vào `knowledge/`. LLM không bao giờ tự ghi.

### F13 — Order và sổ cái cấp đội hình
Một order là hạn mức **sau thuế** cộng thời hạn. Số phải gửi được tính ngược lên từ thuế và
làm tròn lên, để không bao giờ giao thiếu.

Game cho phép chuyển hết, nên **không có trần từng lần giao**. Ràng buộc thật là chính order,
đo bằng **tổng của toàn đội**. Do đó sổ cái — không phải kiểm tra từng hành động — là cơ chế
an toàn: mỗi bút toán bắt buộc có tham chiếu bằng chứng, và biên nhận gửi lệnh không phải
bằng chứng chuyển hàng.

*Đã hiện thực: `autorok/mission/order.py`.*

### F14 — Đội hình và xoay vòng hai cấp
Mỗi nhân vật 5 đạo quân. Chỉ vào lại một nhân vật khi **cả 5 đạo đã về**. Năm đạo không về
cùng lúc, nên chu kỳ khấu hao theo **đạo chậm nhất**; đuôi trống được hấp thụ bằng cách xoay
sang nhân vật kế tiếp, không phải bằng cách vào lại sớm.

Xoay vòng ưu tiên tài khoản đang mở, vì đổi nhân vật rẻ còn đổi tài khoản thì không. Số lượng
tài khoản và nhân vật là **đầu vào lúc chạy**, không phải hằng số trong code.

"Hàng đợi đầy" đo ở **cấp đội hình**: một nhân vật cạn dần là bình thường, đội hình mới là
thứ phải luôn bão hoà.

*Đã hiện thực: `autorok/mission/fleet.py`.*

### F15 — Thang suy giảm
Fail-closed ở **cấp hành động**, không bao giờ dừng ở **cấp vòng lặp**:

```
ORDER_WORK → DEFAULT_FARM → SCARCITY_FILL → DAILY_CITIZEN → OBSERVE_ONLY
```

Hành động bị chặn thì tụt bậc, không đứng hình. Mỗi lần tụt ghi lại kèm lý do; tụt bậc kéo
dài là bằng chứng về vương quốc và phải được đưa lên LLM, không bị nuốt im.

*Bậc `SCARCITY_FILL` đã hiện thực: `autorok/mission/allocation.py`.*

### F16 — Onboarding của LLM local
Sáu pha trước khi được ra bất kỳ quyết định hành động nào: nạp `knowledge/` · xác định vị trí
· khảo sát nhân vật nếu chưa có profile · dựng trạng thái đội hình · xác định mục tiêu hiệu
lực · kiểm tra buff.

Chỉ pha 0 được phép chặn toàn bộ. Các pha khác hỏng thì tụt bậc theo F15.
**Không bao giờ tồn tại trạng thái "không có mục tiêu".**

*Đặc tả đầy đủ: [`docs/LLM_GAMEPLAY_SPEC.md`](LLM_GAMEPLAY_SPEC.md).*

### F17 — Giao hàng như bài toán logistics *(khoá)*
Giao không phải một cú bấm. Người nhận là một người chơi được chỉ định, phải **tele lại gần**
trước, và thông lượng bị chặn bởi **cấp Chợ**: hàng mỗi lượt × số xe, trong đó số xe chính là
một hàng đợi thứ hai độc lập với 5 đạo quân.

**Trạng thái: khoá.** Chưa quan sát được bảng *cấp Chợ → hàng mỗi lượt*, chưa chọn đường giao,
chưa có số thuế. Không xây nửa vời.

---

## 6. Yêu cầu phi chức năng

| Mã | Yêu cầu | Ngưỡng | Hiện trạng |
|---|---|---|---|
| N01 | Chỉ CPU/RAM | không OpenCL, không CUDA | **đạt** |
| N02 | Độ trễ OCR một khung hình | < 400 ms | **chưa đạt** — 4.525 ms |
| N03 | Độ trễ phát input | < 5 ms | **đạt** — < 1 ms (SendInput) |
| N04 | Độ trễ một quyết định LLM | < 10 s | **chưa đạt** — trung vị 20,6 s |
| N05 | Không input ngoài ý muốn | 0 | **đạt** — có bằng chứng G1 |
| N06 | Bằng chứng bất biến | 100% occurrence | **đạt** |

N02 và N04 là hai ràng buộc hiệu năng thật của dự án. Chúng nằm ở **OCR** và ở **model**,
không nằm ở tốc độ di chuyển chuột.

---

## 7. Rủi ro

| Rủi ro | Ảnh hưởng | Cách chặn |
|---|---|---|
| Game cập nhật đổi bố cục UI | toàn bộ nối đất sai | F12 phát hiện và dừng; huấn luyện lại |
| Bấm nhầm `YES`/`NO` do đảo màu | tiêu item ngoài ý muốn | F11 bắt buộc nối đất theo nhãn chữ |
| Tiêu tài nguyên ngoài ý muốn | mất tài sản không hoàn tác được | mọi hành động lớp `spend` thuộc quyền người vận hành |
| Bằng chứng và sổ đăng ký kể hai chuyện khác nhau | nghiệm thu sai | một nguồn sự thật duy nhất, tính bằng máy |
| Harness không đủ sâu | LLM chậm và nhiễu | đo N02/N04 và siết dần |

---
