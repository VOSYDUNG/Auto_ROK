# Nghiên cứu: Quadro M1200 có tăng tốc được dự án không

Ngày: 2026-09-20 · Trạng thái: **nghiên cứu ban đầu, chưa kết luận cuối**

Người vận hành muốn dùng Quadro M1200 4 GB MXM (của Dell Precision 7520) để chạy LLM thay
vì chỉ để xuất hình. Tài liệu này ghi lại những gì kiểm được, và một con số làm thay đổi
câu trả lời.

---

## 1. Con số chặn đường

```
gpt-oss-20b MXFP4      11,3 GB
Quadro M1200 VRAM       4,0 GB
                      ─────────
model lớn gấp           2,8 lần
```

Model **không vừa VRAM**. Đây không phải vấn đề tối ưu, mà là vấn đề dung lượng: 7,3 GB
trọng số sẽ phải nằm ở RAM hệ thống dù có GPU hay không.

Điều này đúng với **mọi** GPU 4 GB, không riêng M1200.

## 2. Offload một phần thì sao

llama.cpp cho phép đẩy một phần lớp lên GPU (`-ngl`). Với 4 GB, sau khi trừ ngữ cảnh và
bộ đệm, thực tế nhét được khoảng **8–12 lớp trên tổng 24** của một model 20B.

Vấn đề là kiến trúc, không phải tỉ lệ:

- Mỗi token, kích hoạt phải **đi qua PCIe** giữa phần trên GPU và phần trên CPU, **hai
  chiều, mỗi lớp biên**
- M1200 là **Maxwell GM107**, 640 nhân CUDA, băng thông bộ nhớ ~80 GB/s
- Xeon E5-2686 v4 có 36 luồng và băng thông RAM 4 kênh DDR4 khoảng **60–70 GB/s**

Tức GPU này **không nhanh hơn CPU kia bao nhiêu về băng thông**, mà lại thêm chi phí qua
PCIe. Với offload một phần trên card Maxwell cũ, kết quả **thường chậm hơn CPU thuần**.

**Cần đo để khẳng định, không kết luận từ lý thuyết.** Nhưng đây là lý do không nên bắt
đầu từ hướng này.

## 3. Trở ngại vật lý: MXM không cắm vào X99

MXM (Mobile PCI Express Module) là chuẩn **module laptop**, không phải card PCIe.

- Máy chạy dự án là bo **X99 desktop** — chỉ có khe PCIe
- Muốn lắp cần **adapter MXM→PCIe**, loại hiếm, và thường kén BIOS/nguồn
- Ngay cả khi lắp được, vẫn vướng con số ở §1

Phương án ngược — chuyển dự án sang **chạy trên laptop 7520** — thì đánh đổi:

| | Xeon X99 (đang dùng) | Precision 7520 |
|---|---|---|
| Luồng CPU | **36** | 8 (Xeon E3-1505M v6, 4C/8T) |
| RAM | **64 GB** | tối đa 64 GB, thường 16–32 |
| GPU | không CUDA | **M1200 4 GB** |

Đổi **36 luồng lấy 4 GB VRAM không đủ chứa model** — gần như chắc chắn là bước lùi cho
suy luận LLM.

## 4. Hướng thật sự đáng đi — và nó miễn phí

Theo kỷ luật của lab: đo trước khi mua. Bốn việc sau chưa làm, và có thể giải quyết phần
lớn 20,6 giây mà **không cần linh kiện nào**.

### 4.1 Kiểm số luồng

llama.cpp mặc định thường lấy số **nhân vật lý**, không phải số luồng. Máy này 18 nhân /
36 luồng. Nếu server đang chạy với 4 hoặc 8 luồng thì đó là toàn bộ câu chuyện.

```bash
llama-server -m C:\AI\models\gpt-oss-20b\gpt-oss-20b-MXFP4.gguf -t 18 --port 8080
```

*Lưu ý:* với suy luận, `-t` bằng **số nhân vật lý** (18) thường tốt hơn số luồng (36), vì
siêu phân luồng hay làm hại workload nghẽn băng thông bộ nhớ. Phải thử cả hai.

### 4.2 Kiểm tập lệnh của bản build

Broadwell có **AVX2**, **không có AVX-512**. Bản WinGet là build chung; cần xác nhận nó
bật AVX2. Nếu không, biên dịch lại với `-DGGML_AVX2=ON` là thay đổi lớn nhất có thể có mà
không tốn tiền.

### 4.3 Tách thời gian nạp và thời gian sinh

20,6 giây hiện là **tổng một lần gọi**. Chưa ai tách:

- nạp model (một lần, nếu server chạy thường trú thì bằng 0)
- xử lý prompt
- sinh token

Nếu phần lớn là nạp model thì giữ server **thường trú** xoá gần hết 20,6 giây. Đây là bản
sao của đúng bài học OCR hôm nay: **4.863 ms phần lớn là chi phí khởi động lặp lại.**

### 4.4 Thử model nhỏ hơn

Vai trò của model ở đây là **bộ chọn có ràng buộc**, không phải trợ lý đa năng. Nó chọn một
ứng viên trong danh sách đã lọc. Đó là việc mà model 3B–7B rất có thể làm được.

Và một model 3B ở Q4 **chỉ khoảng 2 GB** — vừa luôn VRAM 4 GB. Tức con đường dùng được
M1200 là **thu nhỏ model**, không phải mở rộng GPU.

Đây cũng đúng luận đề dự án: nếu giàn giáo đủ sâu thì model nhỏ là đủ.

## 5. Nếu vẫn muốn dùng GPU — cần sửa tuyên bố trước

`docs/PROJECT_DECLARATION.md` §5 hiện ghi ngoài phạm vi: *"Docker, máy ảo, Hyper-V, **mọi
đường chạy phụ thuộc GPU**"*. Và `scripts/audit_goal_readiness.py` cổng G2 đang kiểm
`processing_device=cpu`, `opencl_enabled=False`, `cuda_devices_visible=0`.

Nên dùng GPU **là sửa ranh giới sản phẩm**, phải làm tường minh.

**Đề xuất sửa hẹp, nếu người vận hành muốn:**

> GPU được phép **chỉ cho suy luận LLM**. Đường tri giác — thu hình, OCR, nối đất, phân
> loại trạng thái — **vẫn bắt buộc CPU-only**.

Lý do tách như vậy: điều khoản CPU-only sinh ra để bảo vệ **tính tất định của nối đất**,
tức là chuyện G2 đang kiểm. Suy luận LLM vốn đã không tất định và đã bị ràng buộc bằng hợp
đồng ứng viên. Cho GPU chạy model **không** làm yếu thứ mà luật đó bảo vệ.

Sửa như vậy giữ nguyên ý nghĩa của G2 và mở đúng phần người vận hành cần.

## 6. Ý tưởng coprocessor — đúng tinh thần nhúng

Người vận hành nói về *"kết nối linh kiện để bổ sung năng lực"*, đúng cách hệ nhúng làm:
thêm một con chip cho **một việc cụ thể**.

Nhưng áp vào dự án này thì phải hỏi ngược: **việc nào đủ nặng và đủ tách rời để đáng có
chip riêng?**

| Việc | Chi phí hiện tại | Đáng gắn chip riêng? |
|---|---|---|
| Thu hình | 539 ms | không — đã đủ nhanh |
| Đọc hàng đợi | 0,207 ms | không — template đã gần như miễn phí |
| OCR chữ biến thiên | 4.863 ms | **không** — chi phí là cách gọi, không phải phép tính |
| Suy luận LLM | 20,6 s | **có thể** — nhưng cần ≥ 12 GB VRAM cho model hiện tại |
| Phát input | < 1 ms | không |

Kết luận sơ bộ: **chỉ có đúng một việc nặng**, và nó cần bộ nhớ chứ không cần thêm lõi
tính. Nên hướng coprocessor thật sự là *"GPU có đủ VRAM"*, không phải *"thêm một con chip
nhỏ"*.

Một GPU 12 GB trở lên (ví dụ RTX 3060 12 GB) chứa trọn model 11,3 GB. Đó là ngưỡng thật,
và nó nên được đưa ra sau khi §4 đã làm xong — vì có thể sau §4 thì không cần nữa.

---

## 7. Việc tiếp theo cho lab

Theo thứ tự. Ba việc đầu **miễn phí**.

1. Chạy `llama-server` thường trú, đo tokens/giây với `-t 8`, `-t 18`, `-t 36`
2. Xác nhận bản build có AVX2; nếu không, biên dịch lại
3. Tách thời gian nạp / prompt / sinh token trong 20,6 giây
4. Thử một model 3B–7B trên cùng bộ holdout 12 ca, so độ chính xác và độ trễ
5. Chỉ khi 1–4 xong mà vẫn chưa đạt ngưỡng N04 (< 10 s) mới bàn tới phần cứng

## 8. Người vận hành cần chốt

| Câu hỏi | Ảnh hưởng |
|---|---|
| Quadro M1200 đang ở đâu — trong laptop, hay là card rời? | quyết định §3 có khả thi không |
| Có chấp nhận sửa tuyên bố để cho GPU chạy LLM không? | mở hay khoá cả hướng này |
| Model nhỏ hơn có chấp nhận được không, nếu độ chính xác giữ nguyên? | đây là đường rẻ nhất và hợp luận đề nhất |
