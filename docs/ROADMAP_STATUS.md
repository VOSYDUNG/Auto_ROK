# Auto_ROK — điều hướng tiến độ hiện hành

Cập nhật: 2026-09-24

Tài liệu này chỉ là mục lục điều hướng. Nó không chứa bản sao trạng thái, số đo hoặc
roadmap lịch sử. Nguồn hiện hành duy nhất của từng loại thông tin là:

- Ý định, phạm vi và FIRST DONE: [`PROJECT_DECLARATION.md`](PROJECT_DECLARATION.md),
  [`GOAL.md`](GOAL.md), [`PRD.md`](PRD.md).
- Hợp đồng kỹ thuật: [`SRS.md`](SRS.md).
- Thứ tự xây dựng và phụ thuộc: [`BUILD_PLAN.md`](BUILD_PLAN.md).
- Trạng thái runtime đã đo: [`../runtime-status.yaml`](../runtime-status.yaml).
- Đối chiếu bằng chứng với điều kiện nghiệm thu: [`COMPLETION_AUDIT.md`](COMPLETION_AUDIT.md).
- Điều phối công việc hiện tại: [`ROOT.md`](ROOT.md).

Mốc đang theo dõi được định nghĩa tại [`GOAL.md`](GOAL.md) và nghiệm thu tại
[`PRD.md`](PRD.md). Tài liệu này không giữ một bản mô tả hoặc trạng thái thứ hai.

## Chuỗi đọc cho gói tiếp theo

1. ROOT chọn gói offline và ghi rõ acceptance evidence.
2. Builder đọc SRS/graph rồi làm đúng subgraph được giao.
3. ROOT kiểm test, graph và đối chiếu runtime status; chỉ sau đó cập nhật tài liệu này
   nếu điểm điều hướng thay đổi.

Quyết định mở và gói đang chạy nằm trong [`ROOT.md`](ROOT.md); sau khi chốt,
ROOT cập nhật các nguồn sở hữu điều kiện đó, không cập nhật trạng thái tại đây.
