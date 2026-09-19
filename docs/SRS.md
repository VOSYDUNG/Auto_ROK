# SRS — Auto_ROK

Ngày: 2026-09-19 · Phiên bản 1 · Chịu sự điều chỉnh của [`docs/PROJECT_DECLARATION.md`](PROJECT_DECLARATION.md)

Đây là tài liệu cuối trước khi xây. Nhiệm vụ của nó: biến mọi yêu cầu trong `PRD` thành
**mệnh đề kiểm chứng được**, và chỉ ra chính xác cái nào đã có test, cái nào chưa.

Quy ước:

- Mỗi yêu cầu có **mã**, **mệnh đề**, **tiêu chí chấp nhận** (thứ một test có thể kiểm), và
  **nguồn** (mã PRD).
- `ĐÃ KIỂM` = có test đang chạy. `CHƯA KIỂM` = yêu cầu hợp lệ nhưng chưa có test.
  `CHƯA XÂY` = chưa có code.
- Ngưỡng ghi `TBD-OP` là chỗ **người vận hành phải cho số**; không đoán.

---

## 1. Ngữ cảnh

**Sản phẩm.** Một LLM chạy cục bộ vận hành một client Rise of Kingdoms trên đúng một máy
Windows, thông qua một harness xác định.

**Luận đề đang kiểm.** Năng lực = model × giàn giáo. Trong miền có ranh giới, giàn giáo thay
thế được cho dung lượng model.

**Người dùng.** Một người vận hành, sở hữu máy và tài khoản, ngồi cùng máy với game.

**Ràng buộc nền.** Chỉ CPU/RAM · không ảo hoá dưới mọi hình thức · chỉ tương tác qua bề mặt
nhìn-và-bấm của người chơi · không đọc bộ nhớ, không chèn code.

---

## 2. Tiêu chí thành công định lượng

`PRD` §3.1 để trống X và N. Đây là chỗ điền, kèm lập luận.

### 2.1 Vì sao không so sánh bằng một con số duy nhất

Trần là người chơi giỏi. Nhưng con người **ngủ**. Một người chạy chu kỳ 2h15 trên 8 nhân vật
sẽ phải đăng nhập khoảng 85 lượt một ngày — không ai làm vậy.

Nghĩa là hai bên mạnh ở hai trục khác nhau:

| Trục | Ai thắng | Vì sao |
|---|---|---|
| Chất lượng mỗi quyết định | **người** | chọn mỏ, đọc tình huống, xử lý ngoại lệ |
| Thời lượng sẵn sàng | **agent** | không ngủ |

Năng suất thực = chất lượng × thời lượng. Agent **có thể vượt người về tổng sản lượng trong
khi vẫn kém hơn về chất lượng từng quyết định**. Gộp hai trục vào một con số sẽ giấu mất điều
đó. Nên tách.

### 2.2 Các ngưỡng

| Mã | Chỉ số | Ngưỡng đề xuất | Cơ sở |
|---|---|---|---|
| **SC-01** | Chu kỳ lô của agent so với mốc người vận hành | ≤ **1,15×** mốc ghi nhận (2h00–2h30 farm mạnh · 3h30–4h00 farm yếu) | đây là **X**: agent chậm hơn người không quá 15% mỗi lô |
| **SC-02** | Lần LLM vào cuộc ở tầng chiến thuật | ≤ **5** / 100 tick | đây là **N**. Tỉ lệ 80/20 nói về *trách nhiệm*, không phải tần suất gọi; harness sâu thì model hiếm khi cần hỏi |
| **SC-03** | % thời gian hàng đợi đội hình đầy **và** buff ≠ 0 | ≥ **85%** trong 24h | trần người thực tế thấp hơn do phải ngủ; đây là chỗ agent được phép thắng |
| **SC-04** | Giờ chạy tự chủ liên tục không người chạm | thang: **1h → 4h → 15h** | north star; 15h khớp cổng endurance ở `GOAL` |
| **SC-05** | Lần tự phát hiện game đổi | ≥ **1** trước khi tuyên bố đóng phạm vi | nếu luôn bằng 0 thì năng lực này chưa được chứng minh, chỉ được khai báo |
| **SC-06** | Tổng sản lượng ngày so với người vận hành | **TBD-OP** | cần người vận hành cho số thật họ đạt được mỗi ngày |

**SC-01 đến SC-05 là đề xuất của tôi, chờ người vận hành duyệt hoặc sửa.** SC-06 thì tôi
không có dữ liệu để đề xuất.

---

## 3. Yêu cầu

### 3.1 Thu hình — CAP

| Mã | Mệnh đề | Tiêu chí chấp nhận | Nguồn | Trạng thái |
|---|---|---|---|---|
| CAP-001 | Thu đúng vùng client của cửa sổ đích, không kích hoạt, không phát input | Khung thu khớp client rect hoặc window rect; lệch thì từ chối | F01 | ĐÃ KIỂM · `test_windows_capture_backend` |
| CAP-002 | Cửa sổ đích xác định bằng tiêu đề và tên tiến trình, không hardcode | Gọi với tiêu đề khác thì tìm đúng cửa sổ đó | F01 | ĐÃ KIỂM |
| CAP-003 | Nhiều hơn một cửa sổ khớp là lỗi, không phải chọn bừa | Báo lỗi nêu rõ số cửa sổ tìm thấy | F01 | ĐÃ KIỂM |
| CAP-004 | Mỗi khung mang metadata: thời điểm, kích thước, hash, HWND | Thiếu bất kỳ trường nào thì bản ghi không hợp lệ | F01 | ĐÃ KIỂM |
| CAP-005 | Khung trắng hoặc ít thông tin bị từ chối | Độ lệch chuẩn sáng dưới ngưỡng thì báo lỗi | F01 | ĐÃ KIỂM |
| CAP-006 | Chỉ CPU: OpenCL tắt, không thấy thiết bị CUDA | Bản ghi hiệu năng ghi `processing_device=cpu` | N01 | ĐÃ KIỂM · `test_goal_readiness_audit` |

### 3.2 OCR và ngữ nghĩa — OCR

| Mã | Mệnh đề | Tiêu chí chấp nhận | Nguồn | Trạng thái |
|---|---|---|---|---|
| OCR-001 | Lắp hộp từ thành cụm có nghĩa, tất định | Cùng đầu vào cho cùng đầu ra | F02 | ĐÃ KIỂM · `test_ocr_semantics` |
| OCR-002 | Nối đất mục tiêu theo **nhãn chữ chính xác**, không theo màu hay vị trí | Mục tiêu khai báo không khớp chữ thì không nối đất | F02, F11 | ĐÃ KIỂM |
| OCR-003 | Một khung hoàn tất dưới **400 ms** | Đo trên corpus hiện có | N02 | **CHƯA ĐẠT** — đo được 4.525 ms |
| OCR-004 | Tối ưu OCR không được đổi kết quả | Đầu ra sau tối ưu giống hệt trước trên toàn corpus | N02 | CHƯA XÂY |
| OCR-005 | Đầu ra OCR phải là **UTF-8**, không phụ thuộc locale máy | Tên có dấu (`Šárka`) đọc được; đổi locale không làm gãy | F02 | **CHƯA XÂY** — hiện xuất cp1252 |
| OCR-006 | Đọc được chỉ số hàng đợi trên world map | `1/5` tại `x≈1321…1338, y≈116…125` phải ra đúng | F07 | **CHƯA XÂY** — hiện không đọc được |

### 3.3 Trạng thái — STA

| Mã | Mệnh đề | Tiêu chí chấp nhận | Nguồn | Trạng thái |
|---|---|---|---|---|
| STA-001 | Phân loại tất định trong từ vựng đã khai báo | Cùng bằng chứng cho cùng trạng thái | F03 | ĐÃ KIỂM · `test_state_classifier` |
| STA-002 | Thiếu bằng chứng → `UNKNOWN_STATE`, không đoán | Bằng chứng rỗng không bao giờ cho ra trạng thái cụ thể | F03 | ĐÃ KIỂM |
| STA-003 | Bằng chứng cạnh tranh → `AMBIGUOUS_STATE` | Hai ứng viên điểm sát nhau thì không chọn | F03 | ĐÃ KIỂM |
| STA-004 | Bề mặt tiền cảnh che kết quả nền | Overlay hiện thì không trả CITY/WORLD nền | F03 | ĐÃ KIỂM · `test_alliance_main_view_suppression` |
| STA-005 | Hàng đợi nối đất theo **vị trí**, cấm bắt `n/5` toàn khung | Chuỗi `(5/5)` của nhiệm vụ Trade Deal không được nhận là hàng đợi | F07 | **CHƯA XÂY** — mồi giả đã quan sát thấy |

### 3.4 Order và đội hình — MIS

| Mã | Mệnh đề | Tiêu chí chấp nhận | Nguồn | Trạng thái |
|---|---|---|---|---|
| MIS-001 | Số phải gửi tính ngược từ thuế và **làm tròn lên** | Với mọi thuế < 1, gửi đủ số tính ra thì nhận ≥ hạn mức | F13 | ĐÃ KIỂM · `test_mission_order` |
| MIS-002 | Sổ cái cộng dồn toàn đội, không kiểm từng hành động | Bốn nhân vật mỗi người 1/4 hạn mức thì order đóng | F13 | ĐÃ KIỂM |
| MIS-003 | Bút toán không có tham chiếu bằng chứng bị từ chối | Chuỗi rỗng thì báo lỗi | F13 | ĐÃ KIỂM |
| MIS-004 | Order chưa đóng cho tới khi số **thực nhận** đạt hạn mức | Thuế 50%, gửi đúng hạn mức → chưa đóng | F13 | ĐÃ KIỂM |
| MIS-005 | Mỗi nhân vật đúng 5 đạo; slot không đặt trùng | Đạo thứ 6 hoặc slot trùng bị từ chối | F14 | ĐÃ KIỂM · `test_mission_fleet` |
| MIS-006 | Chu kỳ khấu hao theo **đạo chậm nhất** | Ba đạo về 30/75/200 phút → chu kỳ 200 | F14 | ĐÃ KIỂM |
| MIS-007 | Chỉ vào lại nhân vật khi **cả 5 đạo về** | Còn một đạo đang bay thì không đủ điều kiện | F14 | ĐÃ KIỂM |
| MIS-008 | "Hàng đợi đầy" đo ở **cấp đội hình** | Một nhân vật bão hoà chỉ là 5/40 | F14, SC-03 | ĐÃ KIỂM |
| MIS-009 | Xoay vòng ưu tiên tài khoản đang mở | Còn nhân vật đủ điều kiện trong tài khoản mở thì không đổi tài khoản | F14 | ĐÃ KIỂM |
| MIS-010 | Số tài khoản/nhân vật là đầu vào lúc chạy | Không hằng số nào trong `autorok/` mã hoá 2, 4, hay 8 | F14 | ĐÃ KIỂM |
| MIS-011 | Ước lượng và số đo **không được lẫn nhau** | Chu kỳ `MEASURED` không có mẫu thì bị từ chối | F10 | ĐÃ KIỂM |
| MIS-012 | Không có nhân vật đủ điều kiện là **trạng thái chờ**, không phải lỗi | Trả `None` kèm thời điểm đủ điều kiện kế tiếp | F15 | ĐÃ KIỂM |
| MIS-013 | Tiến độ hạn mức = **Total Resources − From Items** (Items → Statistics) | Hiệu số khớp header trong sai số hiển thị 100K | F13 | **CÁCH ĐÃ CÓ** (2026-09-20), chưa nối code |
| MIS-014 | Không dùng header thô, cũng không dùng cột Total thô | Header làm tròn; Total gộp item chưa mở | F13 | CHƯA XÂY |
| MIS-015 | Mỗi lượt vào nhân vật có **trần thời gian**; hết trần thì rời đi | Việc chưa xong xếp hàng cho lượt sau, không cố làm nốt | F14 | **CHƯA XÂY** |
| MIS-016 | Lộ trình ngày **tính từ trạng thái**, không phải lịch cố định | Cùng giờ hai ngày khác nhau có thể cho lộ trình khác nhau | F10 | **CHƯA XÂY** |

### 3.5 Phân bổ và suy giảm — LAD

| Mã | Mệnh đề | Tiêu chí chấp nhận | Nguồn | Trạng thái |
|---|---|---|---|---|
| LAD-001 | Phân bổ giữ tỉ lệ 1:1:1:2, vàng ăn 2 phần | 5 slot → 2 vàng, 1 mỗi loại còn lại | F09 | ĐÃ KIỂM · `test_mission_allocation` |
| LAD-002 | Bù từ số đang bay, không reset tỉ lệ | Vàng đang thừa thì slot mới không vào vàng | F09 | ĐÃ KIỂM |
| LAD-003 | Phân bổ tất định | Hai lần gọi cho cùng kết quả | F09 | ĐÃ KIỂM |
| LAD-004 | Tìm không ra mỏ → **vẫn lấp đầy slot** | Danh sách mỏ rỗng vẫn trả đủ số slot, chế độ `SCARCITY` | F15 | ĐÃ KIỂM |
| LAD-010 | Khan mỏ nhận biết bằng **khung hình không đổi sau khi bấm Tìm kiếm** | Viewport đứng yên trong cửa sổ chờ = không có mỏ | F15 | **CHƯA XÂY** — thuộc tầng tri giác, không phải OCR |
| LAD-005 | Suy giảm chỉ được **nới lỏng**, không siết | Ngưỡng sàn cao hơn ngưỡng ưu tiên thì báo lỗi | F15 | ĐÃ KIỂM |
| LAD-006 | Mỗi slot ghi rõ chế độ và **lý do** | Không assignment nào có lý do rỗng | F15 | ĐÃ KIỂM |
| LAD-007 | Thang 5 bậc `ORDER_WORK → OBSERVE_ONLY` | Bậc bị chặn thì tụt đúng một bậc, không nhảy cóc | F15 | **CHƯA XÂY** |
| LAD-008 | Mỗi lần tụt bậc ghi lý do vào kho đo | Bản ghi có bậc trước, bậc sau, nguyên nhân | F15 | CHƯA XÂY |
| LAD-009 | **Không bao giờ có trạng thái "không có mục tiêu"** | Mọi tổ hợp đầu vào đều trả về đúng một bậc | F15, F16 | CHƯA XÂY |

### 3.6 Biên quyết định LLM — LLM

| Mã | Mệnh đề | Tiêu chí chấp nhận | Nguồn | Trạng thái |
|---|---|---|---|---|
| LLM-001 | Model chỉ nhận sự kiện trong **danh sách cho phép** | Khoá ngoài danh sách không bao giờ xuất hiện trong gói | F05 | ĐÃ KIỂM · `test_local_llm_selector` |
| LLM-002 | Không bao giờ gửi bbox, rect, toạ độ, HWND, PID, đường dẫn, ảnh | Mọi khoá chứa các phần cấm bị loại | F05 | ĐÃ KIỂM |
| LLM-003 | Đầu ra phải ánh xạ về ứng viên **đã tồn tại** | Không khớp thì **từ chối**, không sửa | F05 | ĐÃ KIỂM |
| LLM-004 | `{"action_id": null}` là câu trả lời hợp lệ | Từ chối được xử lý như abstain, không phải lỗi | F05 | ĐÃ KIỂM |
| LLM-005 | Một **mô-đun ranh giới duy nhất** cho cả hai tầng | Không tồn tại danh sách lọc thứ hai trong repo | F05 | **CHƯA XÂY** — hiện có 2 danh sách đã lệch |
| LLM-006 | Tầng chiến lược nhận gói và trả `MissionIntent` | Gói chiến lược có người nhận, không bị vứt | F05 | **CHƯA XÂY** |
| LLM-007 | Tần suất gọi ở tầng chiến thuật ≤ 5/100 tick | Đo trên một phiên chạy thật | SC-02 | CHƯA KIỂM |
| LLM-008 | `retraining_required` phải nêu *cái gì đổi* và *khung hình nào chứng minh* | Thiếu một trong hai thì tín hiệu không hợp lệ | F12 | CHƯA XÂY |
| LLM-009 | Model **không được tự ghi** vào `knowledge/` | Chỉ sinh đề xuất; ghi cần thao tác của người vận hành | F12 | CHƯA XÂY |

### 3.7 Onboarding — ONB

| Mã | Mệnh đề | Tiêu chí chấp nhận | Nguồn | Trạng thái |
|---|---|---|---|---|
| ONB-001 | Sáu pha chạy đúng thứ tự trước mọi quyết định hành động | Bỏ qua pha nào thì không được phép ra quyết định | F16 | CHƯA XÂY |
| ONB-002 | **Chỉ pha 0** được phép chặn toàn bộ | Pha 1–5 hỏng thì tụt bậc, không dừng | F16 | CHƯA XÂY |
| ONB-003 | Mục chưa xác minh trong `knowledge/` được liệt kê ra, không im lặng | Khởi động ghi danh sách `UNVERIFIED` | F16 | CHƯA XÂY |
| ONB-004 | Chưa có profile thì khảo sát Tướng · City Hall · Chợ | Ba bề mặt đọc xong mới tính tốc độ farm | F16 | CHƯA XÂY — cần client |
| ONB-005 | Khảo sát hỏng → dùng mốc người vận hành và **ghi rõ đang ước lượng** | Nguồn chu kỳ là `OPERATOR_BASELINE` | F16 | ĐÃ KIỂM (phần kiểu dữ liệu) |

### 3.8 Actuation và xác minh — ACT

| Mã | Mệnh đề | Tiêu chí chấp nhận | Nguồn | Trạng thái |
|---|---|---|---|---|
| ACT-001 | Chỉ phát input khi cửa sổ đúng, foreground ổn định, khung tươi, có phê duyệt | Thiếu một điều kiện thì không phát | F06 | ĐÃ KIỂM · `test_windows_interference_guard` |
| ACT-002 | Độ trễ phát input < 5 ms | Đo trên máy thật | N03 | ĐÃ KIỂM — đo < 1 ms |
| ACT-003 | Không input ngoài ý muốn | Trace ghi `input_emitted=false` ở mọi pha quan sát | N05 | ĐÃ KIỂM · `test_host_input_isolation` |
| ACT-004 | Xác minh bằng **khung hình tươi sau hành động** | Biên nhận gửi lệnh không bao giờ đủ | F07 | ĐÃ KIỂM · `test_gather_replay_evidence` |
| ACT-005 | Hậu điều kiện GATHER là `Queue used` tăng đúng 1 | Tăng 0 hoặc ≥2 đều là thất bại | F07 | ĐÃ KIỂM |
| ACT-006 | Phê duyệt gắn occurrence, không chuyển nhượng | Occurrence mới cần phê duyệt mới | G4 | ĐÃ KIỂM · `test_troop_policy` |

### 3.9 Bằng chứng — EVI

| Mã | Mệnh đề | Tiêu chí chấp nhận | Nguồn | Trạng thái |
|---|---|---|---|---|
| EVI-001 | Bản ghi append-only; trùng đường dẫn thì fail-closed | Không ghi đè bản ghi cũ | F08 | ĐÃ KIỂM |
| EVI-002 | Mọi bản ghi gắn danh tính mission/task/run/character | Thiếu trường nào thì không hợp lệ | F08 | ĐÃ KIỂM |
| EVI-003 | Trạng thái dự án **được tính**, không viết tay | `audit_goal_readiness.py` là nguồn duy nhất | §6.2 Tuyên bố | ĐÃ KIỂM · `test_goal_readiness_audit` |
| EVI-004 | G6 cần uỷ quyền tường minh của người vận hành | Thiếu file uỷ quyền thì `blocked` | G6 | ĐÃ KIỂM · `test_r3_endurance_authorization` |

### 3.10 An toàn và ranh giới — SAF

| Mã | Mệnh đề | Tiêu chí chấp nhận | Nguồn | Trạng thái |
|---|---|---|---|---|
| SAF-001 | Không có Docker, máy ảo, Hyper-V, GPU trong mã nguồn sản phẩm | Quét từ vựng, miễn trừ khai theo từng dòng | §5 Tuyên bố | ĐÃ KIỂM · `test_no_virtualization` |
| SAF-002 | Không dùng dịch vụ CI | Không tồn tại file workflow | §5.1 Tuyên bố | ĐÃ KIỂM |
| SAF-003 | Tuyên bố và GOAL **vẫn còn** ghi điều khoản cấm | Nới lỏng tài liệu thì test đỏ | §5.1 Tuyên bố | ĐÃ KIỂM |
| SAF-004 | Hộp xác nhận nối đất theo nhãn chữ, không theo màu/vị trí | `YES` đỏ bên trái, `NO` xanh bên phải — ngược quy ước | F11 | CHƯA XÂY |
| SAF-005 | Hành động tiêu gem thuộc quyền người vận hành | Agent chỉ được đề xuất | §3.3 PRD | CHƯA XÂY |
| SAF-006 | Không lưu thông tin đăng nhập dạng chữ thường trong repo | Quét không thấy trường mật khẩu | §3.3 PRD | CHƯA KIỂM |

### 3.11 Giao hàng — DEL *(toàn bộ đang KHOÁ)*

| Mã | Mệnh đề | Tiêu chí chấp nhận | Nguồn | Trạng thái |
|---|---|---|---|---|
| DEL-001 | Năng lực giao = sức chứa/chuyến × số slot dành cho vận chuyển | Chợ cấp 25 → **10.000.000 net/chuyến**; **5 slot dùng chung với farm** | F17 | **ĐÃ GIẢI** · `test_mission_transport` |
| DEL-010 | Vận chuyển dùng **chung 5 slot** với farm, không phải hàng đợi riêng | Slot đã cấp cho vận chuyển thì không farm được | F14, F17 | ĐÃ KIỂM |
| DEL-011 | Thời gian đi là **một chiều**, phụ thuộc khoảng cách | Gần ≤10s/chiều · xa quan sát được 31 phút/chiều | F17 | ĐÃ KIỂM |
| DEL-012 | **Tele lại gần TRƯỚC khi giao** | Cùng 175 chuyến: ~29 phút gần so với ~90 giờ xa, chênh ~180 lần | F17 | **CÁCH ĐÃ CÓ** (2026-09-20) |
| DEL-013 | Teleport là **vật phẩm tiêu hao**, tele một lần mỗi chiến dịch | Targeted 77 · Territorial 5; tele mỗi chuyến sẽ cạn | F17 | CHƯA XÂY |
| DEL-014 | Ô đích phải đọc `Unoccupied` trước khi tele | Ô có chủ thì không tele được | F17 | CHƯA XÂY |
| DEL-015 | `Teleport` và `March` nối đất theo **nhãn chữ** | Hai nút cạnh nhau, cùng kích thước và màu; bấm nhầm là gửi quân | F17, F11 | CHƯA XÂY |
| DEL-002 | Tele lại gần là chi phí trả **trước**, nằm trong kế hoạch | Kế hoạch giao gồm bước tele | F17 | KHOÁ |
| DEL-003 | Người nhận nối đất trên khung hiện tại, không nhớ | Người nhận cũ không được tái dùng | F17 | KHOÁ |
| DEL-004 | Số đã giao xác minh bằng tồn kho sau chuyển | Biên nhận không đủ | F17 | KHOÁ |
| DEL-005 | Thuế | **8%** tại Chợ cấp 25, đọc từ panel info | F13 | **ĐÃ CÓ SỐ** |
| DEL-006 | Sức chứa 10M là **số thực nhận**, người gửi trả 10.869.565 | Panel: 10.869.565 − 869.565 = 10.000.000, thanh đầy | F17 | **ĐÃ GIẢI** · `test_mission_transport` |
| DEL-007 | Thuế tính bằng **số nguyên**: `floor(gross × pct / 100)` | `gross × 0,92` lệch 1 đơn vị trên chính ca quan sát được | F17 | ĐÃ KIỂM |
| DEL-008 | Sức chứa là **một bể dùng chung** cho cả 4 loại tài nguyên | Đổ đầy bằng ngô thì không còn chỗ cho gỗ/đá/vàng | F17 | ĐÃ KIỂM |
| DEL-009 | Số chuyến = net / sức chứa, **không** gross rồi mới chia | Gross trước làm phồng kế hoạch ~8% (1.522 thay vì 1.400) | F17 | ĐÃ KIỂM |

---

## 4. Bảng truy vết — cái gì còn thiếu

| Nhóm | Tổng | ĐÃ KIỂM | CHƯA KIỂM | CHƯA XÂY | KHOÁ / chờ |
|---|---|---|---|---|---|
| CAP thu hình | 6 | 6 | — | — | — |
| OCR | 6 | 2 | — | 4 | — |
| STA trạng thái | 5 | 4 | — | 1 | — |
| MIS order/đội hình | 16 | 12 | — | 4 | — |
| LAD suy giảm | 10 | 6 | — | 4 | — |
| LLM biên quyết định | 9 | 4 | 1 | 4 | — |
| ONB onboarding | 5 | 1 | — | 4 | — |
| ACT actuation | 6 | 6 | — | — | — |
| EVI bằng chứng | 4 | 4 | — | — | — |
| SAF an toàn | 6 | 3 | 1 | 2 | — |
| DEL giao hàng | 15 | 6 | — | 4 | 5 |
| **Tổng** | **89** | **55** | **2** | **27** | **5** |

**Đọc bảng này:** 55/89 yêu cầu đã có test đang chạy. Phần chưa xây tập trung đúng bốn chỗ —
**thang suy giảm** (LAD-007…010), **tầng chiến lược của LLM** (LLM-005…009),
**onboarding** (ONB-001…004), và **lịch biểu động** (MIS-013…016). Ba nhóm đầu là P1 trong
`BUILD_PLAN`; nhóm thứ tư là mới, sinh ra từ buổi 2026-09-20.

Nhóm ACT, EVI, CAP, STA phủ kín — đó là phần harness đã trưởng thành.

---

## 5. Cách nghiệm thu

| Loại | Cách |
|---|---|
| Yêu cầu logic thuần | test tự động, chạy bằng `python scripts/check_local.py` |
| Yêu cầu hiệu năng | đo trên máy người vận hành, ghi vào `workspace/evidence/` |
| Yêu cầu cần client | pass quan sát an toàn, không phát input |
| Yêu cầu có rủi ro tài sản | người vận hành phê duyệt từng occurrence |
| Trạng thái tổng | `python scripts/audit_goal_readiness.py` — nguồn duy nhất |

Không dùng dịch vụ CI. Mọi kiểm tra chạy trên máy người vận hành.

---

## 6. Mục cần người vận hành cho số

| Mã | Cần gì |
|---|---|
| SC-01…SC-05 | duyệt hoặc sửa ngưỡng tôi đề xuất |
| SC-06 | sản lượng ngày thực tế người vận hành đạt được |
| MIS-015 | trần thời gian mỗi lượt vào nhân vật — **sau khi đo**, không chốt trước |

Đã có đáp án ngày 2026-09-20: ~~DEL-005 thuế~~ (8%) · ~~MIS-013 cách đọc tồn kho~~ ·
~~DEL-006 ngữ nghĩa sức chứa~~ · ~~§7 phép tính 1.522~~.

---

## 7. Phép tính đơn hàng — đã đóng

Nghi vấn "1.522 chuyến" nêu ngày 2026-09-19 đã được ảnh Resource Assistance giải quyết.

**Sai ở đâu:** tôi gross-up rồi mới chia cho sức chứa. Nhưng sức chứa **đã là số thực
nhận**, nên chia thẳng:

```
net cần giao : 14.000.000.000
sức chứa     : 10.000.000 net/chuyến
số chuyến    : 1.400          (không phải 1.522)
tồn kho cần  : 15.217.391.304 gross
```

**Và 1.400 chuyến không hề vô lý.** Với thời gian đi 31 phút quan sát được, giả định khứ hồi
và 8 nhân vật chạy song song:

| Số xe / nhân vật | Toàn đội mỗi ngày | Xong 14B sau |
|---|---|---|
| 1 | 1,86B | **7,5 ngày** |
| 2 | 3,72B | 3,8 ngày |
| 3 | 5,57B | 2,5 ngày |

### Cập nhật 2026-09-20 — bảng trên đã lỗi thời

Hai câu trả lời của người vận hành làm bảng trên sai: **số xe chính là 5 slot farm** (không
có hàng đợi riêng), và **31 phút là một chiều, ở cự ly xa cố ý**. Gần thì tối đa 10s/chiều.

| Khoảng cách | 175 chuyến/nhân vật, 2/5 slot |
|---|---|
| **Gần (10s/chiều)** | **≈29 phút** |
| Xa (31 phút/chiều) | ≈90 giờ |

Chênh **~180 lần**. Nên hành động có đòn bẩy cao nhất trong cả việc giao hàng là **tele lại
gần**, không phải tối ưu cách xếp hàng hay thứ tự chuyến.

Và vì slot dùng chung, mỗi chuyến vận chuyển là một slot **không farm**. Bù lại: một slot
dành cho vận chuyển gần trong đúng một chu kỳ farm (2h15) chuyển được ~405 chuyến ≈ **4,0B**
— đổi một chu kỳ farm lấy 4 tỉ tài nguyên là đổi rất lợi.

Cả ba luật số học đã ghim bằng test trong `tests/test_mission_transport.py`, dùng đúng các
con số đọc từ client.
