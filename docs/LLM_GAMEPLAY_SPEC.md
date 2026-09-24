# Đặc tả gameplay — LLM local

Cập nhật: 2026-09-23 · Chịu sự điều chỉnh của [`docs/PROJECT_DECLARATION.md`](PROJECT_DECLARATION.md)
· Kiến trúc: [`docs/DESIGN_BRIEF.md`](DESIGN_BRIEF.md)

Đây là đặc tả **LLM local chơi game như thế nào** — từ lúc khởi động nguội cho tới vòng vận
hành thường trực sau FIRST DONE. Đây là hợp đồng chuyên môn cho biên quyết định của model;
nó không định nghĩa lại mục tiêu, nghiệm thu hay quyền input của harness.
Model cụ thể được chọn bằng cấu hình runtime; tài liệu này không ghim tên,
kích thước hay bảo đảm một model đã đạt khả năng. FIRST DONE và quyền phiên theo
[`GOAL`](GOAL.md)/[`PRD`](PRD.md); mức chứng minh theo
[`runtime-status`](../runtime-status.yaml).

---

## 1. LLM local là ai trong hệ thống này

**Nó là người ra quyết định trên tri thức đã có, không phải người biết mọi thứ.**

Model biên giới phải nhồi cả thế giới vào trọng số vì không biết trước sẽ gặp gì. Ở đây ta
biết trước. Nên phần "biết" được đẩy ra ngoài — vào harness (cơ chế) và `knowledge/` (tri
thức game) — và để lại cho model đúng phần **suy luận trên tri thức đang có**.

Luận đề cần đo là một model local phù hợp có thể làm tốt phần lựa chọn hẹp nhờ
tri thức và harness. Kích thước model không tự chứng minh năng lực; holdout và
vận hành có hậu kiểm mới là bằng chứng.

### Nó được phép làm

1. Chọn đúng một ứng viên trong tập harness đã lọc sẵn
2. Trả `NEEDS_DECISION` khi bằng chứng không đủ
3. Phát `retraining_required` khi nhận ra bề mặt game đã thay đổi

### Nó không bao giờ được

- nhìn toạ độ màn hình, bbox, HWND, PID, đường dẫn file, ảnh thô
- tự bịa hành động, mục tiêu, hay tham số ngoài tập đã lọc
- giữ đồng hồ, quyết định lịch, hay tự khởi động một chu kỳ
- tiêu tài nguyên, tiêu gem, hay phát chuột/phím

Ranh giới này cưỡng chế bằng **danh sách cho phép** trong `autorok/llm/boundary.py`, không
phải bằng lời dặn trong prompt.

### Luôn bật ≠ luôn có việc

Dịch vụ model chạy thường trực như người quan sát rảnh. Harness chỉ gửi gói khi có tín hiệu
thật. Không có tín hiệu thì nó ngồi im, và **hệ thống vẫn chạy** — vì
`MissionScheduler.tick()` được thiết kế để chạy không cần model.

---

## 2. Onboarding — sáu pha từ khởi động nguội

Onboarding là chuỗi LLM phải đi qua **trước khi được phép ra bất kỳ quyết định hành động
nào**. Mỗi pha có điều kiện hoàn thành rõ ràng. Pha nào hỏng thì tụt bậc theo thang ở §5,
không đứng hình.

### Pha 0 — Nạp bộ não thứ hai

Đọc toàn bộ `knowledge/*.yaml` vào ngữ cảnh làm việc:

| File | Cho biết |
|---|---|
| `farming_workflow_2026-09-19.yaml` | quy trình: order, xoay vòng, chu kỳ lô, chính sách mặc định |
| `gathering_continuity_2026-09-19.yaml` | buff cộng dồn, đường dùng item, bẫy YES/NO đảo màu |
| `courier_station_2026-09-19.yaml` | cửa hàng, chu kỳ xoay hàng, ranh giới chi tiêu |
| `operator_training_*.yaml`, `official_gameplay_guide_*.yaml` | tri thức game nền |

**Hoàn thành khi:** mọi file parse được, và mọi mục `NEEDS_CONFIRMATION` / `UNVERIFIED` được
liệt kê ra. Chúng không chặn, nhưng LLM phải **biết mình đang không biết gì**.

**Hỏng thì:** dừng hẳn. Không có bộ não thứ hai thì không có micro AGI. Đây là pha duy nhất
được phép chặn toàn bộ.

### Pha 1 — Xác định đang đứng ở đâu

Harness thu một khung hình, phân loại trạng thái. LLM nhận trạng thái đã phân loại, không
nhận pixel.

**Hoàn thành khi:** trạng thái ∈ từ vựng đã biết, và `character_id` đọc được.

**Hỏng thì:** `UNKNOWN_STATE` → đây chính là một trong hai tín hiệu LLM được phép xử lý.
Nó đề xuất một hành động điều hướng an toàn (ESC, đóng panel) để về trạng thái đã biết.
Ba lần không về được → `retraining_required`.

### Pha 2 — Khảo sát nhân vật, nếu chưa có profile

Tra `operator_layer` xem `character_id` này đã có `OperatorSnapshot` chưa.

Chưa có thì khảo sát ba bề mặt:

| Bề mặt | Lấy gì | Dùng để |
|---|---|---|
| Tướng | danh sách tướng gom, cấp, skill | thành phần skill của tốc độ farm |
| City Hall | tốc độ farm nền (**chưa cộng skill tướng**) | thành phần nền |
| Chợ | cấp chợ, hàng mỗi lượt, số xe | năng lực giao |

```
tốc độ farm   = nền (City Hall) + đóng góp skill tướng
năng lực giao = hàng mỗi lượt (cấp Chợ) × số xe
```

Mỗi giá trị là một `ObservedFact` gắn khung hình đã đọc. Giá trị suy ra mang `evidence_keys`
của các fact gốc — hợp đồng `operator_layer/profile.py` đã cưỡng chế sẵn.

**Hoàn thành khi:** profile có đủ tốc độ farm; năng lực giao là tuỳ chọn ở pha này.

**Hỏng thì:** dùng mốc kinh nghiệm của người vận hành (`OPERATOR_BASELINE`, 2h15 hoặc 3h45)
và **ghi rõ đang dùng ước lượng**. Không chặn.

### Pha 3 — Dựng trạng thái đội hình

Đọc bảng Troops của nhân vật hiện tại: mỗi dòng cho toạ độ mỏ, cặp tướng, số quân, và
**thời gian đào còn lại**.

Lưu ý ngữ nghĩa quan trọng: đồng hồ `Gathering HH:MM:SS` là **thời gian đào còn lại, không
gồm đường về**. Thời gian về phải suy từ số đo đã lưu, không có trên màn hình.

**Hoàn thành khi:** biết mỗi nhân vật còn mấy slot trống và khi nào cả lô về hết.

**Hỏng thì:** coi nhân vật là *chưa biết*, không đưa vào vòng xoay cho tới khi đọc được.

### Pha 4 — Xác định mục tiêu đang hiệu lực

Theo thứ tự:

1. Có order người vận hành giao còn hạn? → `ORDER_WORK`
2. Không có? → `DEFAULT_FARM` với tỉ lệ 1:1:1:2

Tầng lập kế hoạch luôn có một mục tiêu dự phòng, nhưng mục tiêu đó không tự cho
phép phát input. Người vận hành có thể đổi mục tiêu hoặc dừng/thu hồi quyền phiên;
thiếu quan sát hay quyền hợp lệ thì hành động vẫn phải `HOLD`.

### Pha 5 — Kiểm tra buff trước khi lập lịch

Đọc thời gian còn lại của buff tăng tốc thu thập.

Đây **không phải** kiểm tra năng suất — nó là **đầu vào của lịch biểu**. Cả hai mốc chu kỳ
đều giả định buff 50% đang chạy. Buff tắt thì chu kỳ giãn ra và toàn bộ lịch xoay vòng sai.

**Hoàn thành khi:** biết buff còn bao lâu, hoặc biết chắc nó đã tắt.

→ Onboarding xong. Vào vòng vận hành.

---

## 3. Vòng vận hành — hai nhịp

### Nhịp chiến lược (mỗi chu kỳ lập kế hoạch, đơn vị phút)

Câu hỏi: *bây giờ vào nhân vật nào, làm gì?*

**Gói gửi LLM** (`MissionIntentRequest`):

```json
{
  "cycle_id": "...",
  "active_goal": "ORDER_WORK",
  "order": {
    "order_id": "...", "remaining_hours": 214.5,
    "outstanding_net": {"FOOD": 1200000000, "GOLD": 3100000000},
    "on_pace": false
  },
  "fleet": {
    "queue_occupancy": 0.72,
    "eligible_characters": ["acc-0-char-2", "acc-1-char-0"],
    "next_eligible_at_seconds": 1850
  },
  "buff": {"gather_speed_remaining_seconds": 5400},
  "daily": {"vip_unclaimed": true, "alliance_donations_left": 14},
  "candidates": [
    {"intent_id": "ENTER_CHARACTER", "character_id": "acc-0-char-2"},
    {"intent_id": "TOP_UP_BUFF", "quantity": 1},
    {"intent_id": "CLAIM_DAILY", "task_id": "CLAIM_VIP"}
  ]
}
```

**Trả về:** `{"intent_id": "...", "...tham số trong ứng viên..."}` hoặc
`{"intent_id": null, "reason": "..."}`.

20,6 giây ở đây **không phải vấn đề** — harness đang chờ quân về hàng giờ.

### Nhịp chiến thuật (mỗi tick, đơn vị giây)

Câu hỏi: *trong màn hình này, bấm ứng viên nào?*

Đây là đường đã chạy: `OpenAICompatibleDecisionProvider.choose()` nhận `ToolSnapshot` đã
lọc, trả một `ActionChoice`.

**Nguyên tắc ngược chiều:** ở tầng này, sự tham gia của model phải **giảm dần**. Selector tất
định xử lý mọi trạng thái rõ ràng; chỉ gọi model khi thật sự bế tắc. Chỉ số
`local_llm_entries_per_100_ticks` đo đúng điều đó — càng thấp, harness càng sâu.

20,6 giây ở đây **là** vấn đề, vì nó nằm trên đường tới hạn.

---

## 4. Ba cách trả lời, và khi nào dùng cái nào

### 4.1 Chọn một ứng viên

Khi bằng chứng đủ để phân biệt. Chỉ được chọn thứ có trong danh sách; đầu ra được ánh xạ
ngược về đối tượng harness đã tạo. Không khớp thì bị từ chối, không phải bị sửa.

### 4.2 `NEEDS_DECISION`

Khi bằng chứng **không đủ để phân biệt**. Đây là câu trả lời đúng, không phải thất bại.

Dùng khi: hai ứng viên không phân biệt được bằng dữ kiện đang có · dữ kiện cần thiết vắng
mặt · dữ kiện mâu thuẫn nhau.

**Không dùng khi:** chỉ vì hành động có vẻ rủi ro — rủi ro là việc của chốt chặn harness,
không phải của model.

### 4.3 `retraining_required` — việc chỉ LLM làm được

Giống người chơi thật: thứ xưa nay vẫn làm được nay không làm được nữa, hoặc một màn hình
biến mất một thời gian.

Kích hoạt khi:

| Dấu hiệu | Ví dụ |
|---|---|
| Control mong đợi vắng mặt | không thấy nút `USE` hay tab `BOOSTS` trên khung hình tươi |
| Nhãn đã đổi | tên item hoặc mô tả khác với bản ghi trong `knowledge/` |
| Hộp thoại đổi hình dạng | hộp xác nhận thêm hoặc bớt nút |
| Bề mặt vắng kéo dài | Courier Station không vào được qua nhiều lần kiểm theo lịch |
| Kế hoạch suy giảm kéo dài | `is_degraded()` đúng liên tục nhiều chu kỳ |

**Bắt buộc:** nêu *cái gì đã đổi* và *khung hình nào chứng minh*. Cấm đoán mục tiêu thay thế.

**Mở rộng — bộ não thứ hai tự viết:** khi phát hiện thay đổi, LLM được phép **đề xuất** một
`ObservedFact` mới kèm bằng chứng. Người vận hành duyệt một cú thì nó vào `knowledge/`. LLM
**không bao giờ** tự ghi. Đây là thứ biến micro AGI từ *được người nuôi* thành *tự nuôi*, và
chỉ số của nó là: *bao nhiêu phần trăm tri thức của một miền mới do hệ thống tự đề xuất?*
Hôm nay = 0%.

---

## 5. Thang suy giảm — không bao giờ đứng hình

Người vận hành: *"tôi tác động nó thay đổi các quyết định thôi chứ không làm nó dừng vận
hành"*.

```
1. ORDER_WORK      làm theo hạn mức được giao
2. DEFAULT_FARM    tỉ lệ 1:1:1:2, mỏ cấp cao xuống thấp
3. SCARCITY_FILL   bỏ ưu tiên cấp và loại, miễn lấp đầy hàng đợi
4. DAILY_CITIZEN   VIP, quà, Courier Station, đóng góp liên minh theo nhịp hồi
5. OBSERVE_ONLY    chỉ quan sát và ghi bằng chứng, không phát input
```

Bậc 3 là **luật khan mỏ** của người vận hành — đã hiện thực trong
`autorok/mission/allocation.py`. Bậc 5 là đáy: hệ thống vẫn sống, vẫn ghi, chờ người.

Quy tắc bất biến hai cấp:

- **Cấp hành động — fail-closed.** Không nối đất được, không phê duyệt được → **không bấm**.
- **Cấp vòng lặp — còn quan sát/ghi nhận.** Hành động bị chặn → ghi lý do và
  có thể về `OBSERVE_ONLY`; không tự phát input ở bậc khác khi quyền công việc hoặc
  safety gate hiện hành không còn hợp lệ. Các bậc mission khác chỉ áp dụng
  sau FIRST DONE với quyền riêng.

Đây đúng là thứ `Mouse_key.py` thiếu: nó không xác minh được hành động và không tụt bậc
được, nên mọi ngoại lệ đều đóng băng cả lifecycle.

Mọi lần tụt bậc ghi lại kèm lý do. Tụt bậc kéo dài là bằng chứng về vương quốc — đưa lên LLM,
không nuốt im.

---

## 6. Ví dụ vận hành

### 6.1 Lấp hàng đợi khi mỏ khan

Đội hình còn 3 slot trống. Tìm kiếm trả về mỏ cấp 5 và 4, ngưỡng ưu tiên là 5.

Harness tính: 2 slot được mỏ ưu tiên, 1 slot không. `plan_slots()` trả 2 `NORMAL` + 1
`SCARCITY`, `is_degraded()` = đúng.

LLM **không được hỏi** — không có mơ hồ nào. Đây là ví dụ policy sau khi sensor,
quyền phiên và chốt input đều đã hợp lệ; hiện tại không được suy điều kiện đó từ
3 slot giả định rồi gửi quân. Tín hiệu suy giảm được ghi; nếu lặp lại nhiều chu
kỳ thì mới báo LLM như bằng chứng về vương quốc.

*Đây là ví dụ về tầng 80% làm việc của nó.*

### 6.2 Buff sắp hết giữa chu kỳ

Buff còn 40 phút. Lô dài nhất đang bay còn 2h10.

Harness biết: mốc chu kỳ giả định buff chạy → lịch sẽ sai. Ứng viên: `TOP_UP_BUFF` số lượng
1 hoặc 2, hoặc hoãn.

Có mơ hồ thật (tiêu bao nhiêu item cho bao nhiêu lợi ích) → **hỏi LLM**. 20 giây là không đáng
kể so với 2h10.

*Đây là ví dụ về 20% xứng đáng.*

### 6.3 Nút USE biến mất

Harness mở Items → `BOOSTS`, chọn item, nhưng khung hình tươi không có control `USE`.

Fail-closed ở cấp hành động: **không bấm gì**. Duy trì buff là mốc farm hằng
ngày sau FIRST DONE; nếu quyền hoặc bằng chứng buff thiếu thì vòng duy trì đó
chuyển `BLOCKED`, có thể quan sát tiếp nhưng không tự chạy `DAILY_CITIZEN`.
Bậc đó cần quyền riêng.

LLM phát `retraining_required` nêu rõ control nào vắng và khung hình nào chứng minh, kèm đề
xuất một `ObservedFact` mô tả bố cục mới — **chờ người vận hành duyệt**.

*Đây là ví dụ về việc chỉ LLM làm được.*

---

## 7. Cấm tuyệt đối

| Cấm | Vì sao |
|---|---|
| Bịa `action_id` hoặc `intent_id` ngoài danh sách | ánh xạ ngược sẽ từ chối; im lặng sửa là tạo hành động ma |
| Đoán toạ độ | model không bao giờ thấy toạ độ; đoán là ảo giác |
| Bấm theo màu hoặc vị trí | hộp xác nhận có `YES` **đỏ bên trái**, `NO` **xanh bên phải** — ngược quy ước. Chỉ nối đất theo **nhãn chữ** |
| Tự ghi vào `knowledge/` | chỉ được đề xuất; người vận hành duyệt |
| Coi biên nhận gửi lệnh là thành công | chỉ hậu điều kiện nhìn thấy trên khung hình tươi mới tính |
| Tái dùng phê duyệt cũ cho occurrence mới | phê duyệt gắn occurrence, không chuyển nhượng |
