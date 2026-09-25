# PRD — Auto_ROK

Sản phẩm và nghiệm thu hiện hành · Theo [PROJECT_DECLARATION](PROJECT_DECLARATION.md).
FIRST DONE do người vận hành chốt phạm vi ngày 2026-09-23. Lịch sử sửa đổi nằm trong
Git; bằng chứng đã đạt thuộc [COMPLETION_AUDIT](COMPLETION_AUDIT.md) và
[runtime-status](../runtime-status.yaml), không nằm trong các ô trạng thái của PRD.

---

## 1. Bài toán

Người vận hành muốn một client Rise of Kingdoms duy trì năng suất thu thập tối đa liên
tục 24/24 mà không phải ngồi canh, và muốn phần *quyết định* nằm ở một mô hình chạy cục
bộ chứ không phải ở một chuỗi toạ độ viết cứng.

Đường cũ (`Mouse_key.py`) đã chứng minh cách làm sai: toạ độ cứng, `time.sleep`, không đo,
không xác minh. Nó không thể tự biết mình đúng hay sai, nên không thể giao cho nó chạy
không người trông.

## 2. Người dùng

Một người vận hành duy nhất, sở hữu máy và tài khoản. Người này cấu hình/ủy quyền
phiên farm, cung cấp kiến thức game và giữ quyền với hành động tiêu tài sản.
FIRST DONE không cần người đó duyệt từng lượt điều quân; cơ chế quyền phiên có
giới hạn phải được thiết kế và kiểm chứng trước khi chạy live.

## 3. Phạm vi (Scope)

### 3.1 Luận đề đang kiểm

> **Năng lực = model × giàn giáo.** Trong một miền có ranh giới, giàn giáo thay thế được cho
> dung lượng model.

Phát biểu để có thể sai:

> Với cùng một model local được chọn tại thời điểm đo, harness đưa hiệu suất vận
> hành từ *không chạy nổi* lên *trong khoảng X% mốc người chơi giỏi*, trong khi
> model vào cuộc dưới N lần / 100 tick.

Model, phần cứng, X và N là tham số của phép đo, không phải hằng số hay điều
kiện nghiệm thu FIRST DONE. Cấu hình runtime chọn model có thể thay thế; mọi
kết quả benchmark ghi lại model đã dùng để so sánh được.

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

**FIRST DONE** chỉ lấy một vòng `GATHER_RESOURCE` của một nhân vật: tự điều
quân 5 đạo bằng cặp New Troop được game tự điền và xác minh hàng đợi 5/5. Tự nhận diện quân về,
nạp lại, duy trì buff và chạy 24 giờ là phạm vi sản phẩm về sau.

| Hạng mục | Nội dung |
|---|---|
| Miền | Rise of Kingdoms, **một máy Windows thật**, một client hiển thị |
| Đội hình | nhiều tài khoản × nhiều nhân vật × 5 đạo quân; hiện 2×4×5, **số lượng là đầu vào lúc chạy** |
| Xoay vòng | đổi nhân vật trong game (Settings → Character), **không cần thông tin đăng nhập** |
| Mission | `ACCUMULATE` theo hạn mức + thời hạn; `DEFAULT_FARM` tỉ lệ 1:1:1:2; `DAILY_CITIZEN` |
| Suy giảm | thang 5 bậc, `SCARCITY_FILL` khi khan mỏ |
| Giao hàng | **trong phạm vi sau FIRST DONE nhưng đang KHOÁ** — đã có phép đo Chợ cấp 25; còn thiếu bảng cấp Chợ đầy đủ và đường giao live có hậu kiểm |
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

### 3.4 Nghiệm thu FIRST DONE và mốc sản phẩm sau đó

FIRST DONE là **một vòng năm đạo đã xuất phát** của cùng một nhân vật trên một
client. Nhận mốc này chỉ khi đồng thời:

1. Người vận hành cấu hình và ủy quyền một công việc GATHER có giới hạn cho
   đúng nhân vật đang mở; xác nhận một lần lúc cấp job được ràng với frame,
   client và thời điểm khởi đầu. Giá trị `character_id` từ cấu hình đơn lẻ
   không thay bằng chứng đó. Harness tự đi năm đạo trong phạm vi đó, không hỏi duyệt từng
   march. Quyền công việc không mở tài khoản, mật khẩu, xóa tài khoản, chuyển
   tài sản, gem hay item tiêu hao; các hành động rủi ro/ngoài GATHER cần quyết
   định riêng. Mỗi dispatch được kiểm scope, đúng cửa sổ và quan sát tươi.
2. Trên **mỗi** màn New Troop mở mới, game tự điền cặp chỉ huy theo gợi ý của
   nó. Harness không sửa cặp, chỉ bấm March khi khung hiện tại cho thấy đội
   hình đã điền và nút March hợp lệ, không có can thiệp/đổi selection ngoài
   luồng. Không cần đọc danh tính từng chỉ huy hay chứng minh nhãn xếp hạng
   “best” riêng; thiếu đội hình hoặc state không rõ thì dừng.
3. Năm lần điều quân có chuỗi bằng chứng append-only theo cùng nhân vật/công
   việc. Trước đạo đầu, UI hàng đợi bên phải chưa xuất hiện nên không yêu cầu
   frame 0/5 hoặc suy số 0 từ OCR trống. Hậu kiểm mới sau đạo đầu phải cho 1/5;
   bốn hậu kiểm tiếp theo cho 2/5, 3/5, 4/5, rồi 5/5. `DISPATCHED` không phải
   `VERIFIED`; một ảnh 5/5 cũ hoặc
   một lần có can thiệp tay không đủ chứng minh vòng tự chủ.
4. Báo cáo đóng vòng ghi thời điểm, nguồn và ước lượng thời gian đào/về nếu có;
   ước lượng được phân biệt với số đo và không là điều kiện kết thúc. Không
   cần chờ quân về, nạp lại slot, duy trì buff hay chạy đủ 24 giờ.

Các kiểm tra an toàn G1/G2/G5 liên quan đến đường input và hậu kiểm phải có
bằng chứng đúng occurrence mới trước khi nhận live. G3/B003/R3/G6 trong
[GOAL](GOAL.md) vẫn là audit/benchmark/endurance tương ứng, không biến thành
duyệt thủ công của năm march. Local LLM chỉ được chọn trong ứng viên đã lọc
khi thực sự cần; benchmark/tần suất model không phải cổng giả cho đường
deterministic này.

Mốc **farm mỗi ngày** sau FIRST DONE còn cần tự phát hiện quân trở về, nạp lại,
duy trì buff, đo H1 so với mốc người chơi trên giờ
tự chủ, hàng đợi/buff, tần suất LLM và phát hiện game đổi; `ACCUMULATE` phải
chạy trọn một chu kỳ order kể cả khan mỏ và tụt bậc. Nhiều nhân vật, nhiệm vụ
hằng ngày và các nhánh khác chỉ mở khi lát cắt một nhân vật đã có bằng chứng.
Giao hàng vẫn khoá và không thuộc nghiệm thu hiện tại.

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

**Yêu cầu hiệu năng:** một khung hình phải hoàn tất dưới **400 ms** theo phép đo
được định nghĩa trong [SRS](SRS.md). Số đo và mức chứng minh hiện hành chỉ lấy từ
[COMPLETION_AUDIT](COMPLETION_AUDIT.md) / [runtime-status](../runtime-status.yaml).

### F03 — Phân loại trạng thái
Từ bằng chứng khung hình, phân loại tất định trạng thái UI trong từ vựng đã khai báo.
Thiếu bằng chứng hoặc bằng chứng cạnh tranh nhau thì trả `UNKNOWN_STATE` /
`AMBIGUOUS_STATE`, không đoán.

### F04 — Đồ thị mission và lọc ứng viên
Biên dịch luồng mission đã huấn luyện thành đồ thị runtime, và với mỗi trạng thái, sinh
ra tập hành động hợp lệ đã lọc. Đây là tập mà LLM được phép chọn trong đó.

### F05 — Biên quyết định LLM local
Chỉ gửi gói ngữ cảnh tối thiểu khi có bài toán lựa chọn thực sự và các ứng viên
hợp lệ đã được harness lọc từ bằng chứng tươi. `UNKNOWN_STATE` không cấp quyền
chọn hay phát input: dừng hành động, quan sát lại hoặc báo `retraining_required`.
LLM chỉ được trả một ứng viên có sẵn, `NEEDS_DECISION` hoặc
`retraining_required`. Mọi phản hồi không khớp tập ứng viên, lỗi hoặc timeout
đều bị từ chối và ghi telemetry.

### F06 — Actuation có chốt chặn và quyền phiên
Phát chuột/phím qua Win32 chỉ khi cửa sổ đích đúng, foreground ổn định, khung
hình còn tươi, action/target được grounding chính xác và quyền còn hiệu lực.
Trong FIRST DONE, người vận hành cấu hình/ủy quyền **một công việc năm đạo có
giới hạn** trước khi chạy; quyền này ràng buộc nhân vật, hành động GATHER, tối
đa năm dispatch, điều kiện dừng và log. Harness kiểm lại scope tại mỗi dispatch;
đó là kiểm nội bộ, không yêu cầu duyệt thủ công từng lượt. Quyền theo occurrence
của các phép thử B003 cũ không tự biến thành quyền công việc mới.
Bộ hành động được phép phải là tập con của catalog semantic GATHER đã biên dịch;
chuỗi lạ hoặc hành động ngoài GATHER không thể tự cấp quyền bằng cách ghi vào
artifact công việc. FIRST DONE không cần dùng item; mọi thao tác dùng item ở
mốc sau cần item và mục đích nằm trong quyền riêng.
Bất kỳ điều kiện nào hỏng thì không phát.

### F07 — Xác minh hậu điều kiện
Sau hành động, thu khung hình mới và chứng minh hậu điều kiện đã khai báo. Với
dispatch GATHER khi có slot, `Queue used` tăng đúng 1; FIRST DONE cần năm
postcondition liên tiếp tới 5/5. Phát hiện quân trở về, nạp lại và dùng buff
thuộc mốc sau và có hậu điều kiện riêng gắn quan sát mới. Không đồng nhất
`DISPATCHED` với `VERIFIED` và không lấy biên nhận input làm bằng chứng.

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

### F11 — Liên tục hoá năng suất sau FIRST DONE
Trong mốc farm hằng ngày, đo thời gian hàng đợi đầy và slot trống; khi quân về,
phát hiện và nạp lại theo trạng thái mới trong giới hạn slot trống đã cấu hình
cho phiên. Quan sát thời gian buff còn lại và
duy trì buff tăng tốc thu thập khác 0 khi item đã được phép và có sẵn; nếu
không đủ điều kiện thì dừng đúng chốt, ghi gap, không tuyên bố đạt 24 giờ.
- Buff `8-Hour Enhanced Gathering`: +50%, 8 giờ, **thời lượng cộng dồn** khi dùng thêm.
- Ba item có thể phủ đủ 24 giờ theo thời lượng danh nghĩa; tồn kho và hiệu lực
  thực tế phải được quan sát, không giả định.
- Đường thao tác: mở Items → tab `BOOSTS` → chọn item → đọc khung chi tiết → `USE` →
  xác nhận.
- **Chốt an toàn:** hộp thoại xác nhận có `YES` **màu đỏ bên trái** và `NO` **màu xanh
  bên phải** — ngược quy ước thường gặp. Nối đất bắt buộc theo nhãn chữ, cấm theo màu
  hoặc vị trí. Dùng item phải thuộc quyền phiên đã giới hạn tại F06.

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

Module hợp đồng: `autorok/mission/order.py`; mức chứng minh runtime theo
[runtime-status](../runtime-status.yaml), không suy từ sự tồn tại của file.

### F14 — Đội hình và xoay vòng hai cấp
Mỗi nhân vật 5 đạo quân. Chỉ vào lại một nhân vật khi **cả 5 đạo đã về**. Năm đạo không về
cùng lúc, nên chu kỳ khấu hao theo **đạo chậm nhất**; đuôi trống được hấp thụ bằng cách xoay
sang nhân vật kế tiếp, không phải bằng cách vào lại sớm.

Xoay vòng ưu tiên tài khoản đang mở, vì đổi nhân vật rẻ còn đổi tài khoản thì không. Số lượng
tài khoản và nhân vật là **đầu vào lúc chạy**, không phải hằng số trong code.

"Hàng đợi đầy" đo ở **cấp đội hình**: một nhân vật cạn dần là bình thường, đội hình mới là
thứ phải luôn bão hoà.

Module hợp đồng: `autorok/mission/fleet.py`; mức chứng minh runtime theo
[runtime-status](../runtime-status.yaml).

### F15 — Thang suy giảm
Khi chỉ một hành động bị chặn vì thiếu điều kiện gameplay, tiếp tục vòng quan
sát ở bậc an toàn hơn:

```
ORDER_WORK → DEFAULT_FARM → SCARCITY_FILL → DAILY_CITIZEN → OBSERVE_ONLY
```

Mỗi lần tụt ghi lại kèm lý do; tụt bậc kéo dài là bằng chứng về vương quốc và
phải được đưa lên LLM, không bị nuốt im. Hết quyền phiên, sai cửa sổ/foreground,
không xác định được trạng thái hoặc vi phạm giới hạn an toàn là **điều kiện dừng
phiên**, không được dùng thang suy giảm để tiếp tục phát input.

Module hợp đồng cho `SCARCITY_FILL`: `autorok/mission/allocation.py`; mức chứng
minh runtime theo [runtime-status](../runtime-status.yaml).

### F16 — Onboarding của LLM local
Sáu pha trước khi được ra bất kỳ quyết định hành động nào: nạp `knowledge/` · xác định vị trí
· khảo sát nhân vật nếu chưa có profile · dựng trạng thái đội hình · xác định mục tiêu hiệu
lực · kiểm tra buff.

Ở tầng lập kế hoạch, chỉ pha 0 chặn khởi động; pha khác hỏng thì chọn một mục
tiêu dự phòng theo F15. Mục tiêu dự phòng không cấp quyền hành động: thiếu
quan sát, quyền công việc hoặc chốt an toàn thì hành động GATHER phải dừng/quan sát
an toàn theo F06/F15, không phát input. "Không có mục tiêu" không đồng nghĩa
"luôn có hành động hợp lệ".

*Đặc tả đầy đủ: [`docs/LLM_GAMEPLAY_SPEC.md`](LLM_GAMEPLAY_SPEC.md).*

### F17 — Giao hàng như bài toán logistics *(khoá)*
Giao không phải một cú bấm. Người nhận là một người chơi được chỉ định, phải **tele lại gần**
trước, và thông lượng bị chặn bởi **cấp Chợ** cùng số march dành cho vận chuyển.
Vận chuyển dùng **chung 5 slot march với farm**, không có hàng đợi thứ hai;
slot vận chuyển là slot tạm không farm. Hợp đồng số học tại Chợ cấp 25 được
ghi trong [SRS §7](SRS.md) và kiểm bởi `tests/test_mission_transport.py`.

**Trạng thái: khoá cho live.** Đã quan sát 10M net/chuyến và thuế 8% ở Chợ cấp
25, nhưng chưa có bảng *cấp Chợ → hàng mỗi lượt* đầy đủ, đường giao và hậu
kiểm live. Không suy các cấp khác từ một phép đo hoặc mở nhánh này trước FIRST
DONE.

---

## 6. Yêu cầu phi chức năng

| Mã | Yêu cầu | Ngưỡng |
|---|---|---|
| N01 | Chỉ CPU/RAM | không OpenCL, không CUDA |
| N02 | Độ trễ OCR một khung hình | < 400 ms |
| N03 | Độ trễ phát input | < 5 ms |
| N04 | Độ trễ một quyết định LLM | < 10 s |
| N05 | Không input ngoài ý muốn | 0 |
| N06 | Bằng chứng bất biến | 100% occurrence |

N02 và N04 là hai ràng buộc hiệu năng của sản phẩm. Số đo, môi trường đo và
giới hạn của từng chứng cứ nằm tại [COMPLETION_AUDIT](COMPLETION_AUDIT.md) và
[runtime-status](../runtime-status.yaml), không cập nhật trạng thái ở PRD.

---

## 7. Rủi ro

| Rủi ro | Ảnh hưởng | Cách chặn |
|---|---|---|
| Game cập nhật đổi bố cục UI | toàn bộ nối đất sai | F12 phát hiện và dừng; huấn luyện lại |
| Bấm nhầm `YES`/`NO` do đảo màu | tiêu item ngoài ý muốn | F11 bắt buộc nối đất theo nhãn chữ |
| Tiêu tài nguyên ngoài ý muốn | mất tài sản không hoàn tác được | mọi hành động lớp `spend` thuộc quyền người vận hành |
| Bằng chứng và trạng thái kể hai chuyện khác nhau | nghiệm thu sai | audit G1–G6 tính từ artifact; capability chỉ nâng trong `runtime-status.yaml` theo đúng mức chứng minh |
| Harness không đủ sâu | LLM chậm và nhiễu | đo N02/N04 và siết dần |

---
