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

## 3. Nguyên tắc sản phẩm

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

## 4. Yêu cầu chức năng

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

---

## 5. Yêu cầu phi chức năng

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

## 6. Rủi ro

| Rủi ro | Ảnh hưởng | Cách chặn |
|---|---|---|
| Game cập nhật đổi bố cục UI | toàn bộ nối đất sai | F12 phát hiện và dừng; huấn luyện lại |
| Bấm nhầm `YES`/`NO` do đảo màu | tiêu item ngoài ý muốn | F11 bắt buộc nối đất theo nhãn chữ |
| Tiêu tài nguyên ngoài ý muốn | mất tài sản không hoàn tác được | mọi hành động lớp `spend` thuộc quyền người vận hành |
| Bằng chứng và sổ đăng ký kể hai chuyện khác nhau | nghiệm thu sai | một nguồn sự thật duy nhất, tính bằng máy |
| Harness không đủ sâu | LLM chậm và nhiễu | đo N02/N04 và siết dần |

---

## 7. Ngoài phạm vi phiên bản này

Đổi tài khoản tự động, mua vật phẩm bằng gem, rally quân, điều phối sự kiện, và mọi thứ
chạy ngoài một máy Windows một người dùng.
