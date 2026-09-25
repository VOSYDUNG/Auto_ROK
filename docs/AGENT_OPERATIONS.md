# Vận hành đội agent Auto_ROK

Đọc [ROOT](ROOT.md) và nguồn chuyên môn được giao. Repo giữ vai trò, quyền và giới
hạn song song trong [team.json](../.codex/team.json); ROOT giữ đầu mối điều phối.
Model ROOT là lựa chọn của người dùng trong phiên Codex. Repo dùng profile
`inherit`: không lưu tên model hay mức effort cố định trong team và role files.
Trước **mỗi gói**, ROOT chọn vai trò, model, effort, context và autonomy từ
model thực có và tính chất việc; hỏi người dùng khi một quyết định sản phẩm hoặc
cơ cấu bền vững còn thiếu. Lựa chọn model ROOT thuộc người dùng trong phiên;
không biến menu của một ngày thành chính sách bền hoặc đổi model mặc định toàn máy.

## Cấu trúc trách nhiệm

- ROOT xác định mục tiêu/gói từ [GOAL](GOAL.md), [PRD](PRD.md), [graph](../config/engineering_graph.yaml)
  và bằng chứng; giữ một [báo cáo hiện hành](ROOT.md), kiểm kết quả và quyết định tích hợp.
- Vai `nghien_cuu` khảo sát nguồn và giả định; `tho_dung` sửa phần đã được giao;
  `nguoi_thu` kiểm đầu ra; `kiem_luat` review độc lập khi thay đổi có rủi ro.
  Danh mục vai không bắt phải chạy đủ ghế. Tối đa hai child đồng thời, và không
  vượt slot host. Gói nhỏ hoặc phụ thuộc nối tiếp có thể do ROOT làm trực tiếp.
- Role TOML không tự cấp quyền lên game hay hệ thống ngoài. ROOT giao phạm vi
  node/file rời nhau cho writer; role chỉ đọc không ghi dù tool cho phép. Model
  và effort được chọn cho lần giao đó; thiếu dữ liệu khả dụng thì ghi chưa biết.

Mỗi đề bài có `owned_nodes`, upstream, downstream, acceptance evidence, blocker,
expected graph delta; mục tiêu/lý do, nguồn và commit, file sở hữu, điều loại trừ,
model/effort/context/autonomy của **gói hiện tại**, giới hạn thử và side effect.
Dùng context ngắn tự đủ. Không tạo task Codex của người dùng thay cho subagent.

## Sự kiện, hồ sơ và nghiệm thu

Giao gói khi đủ đầu vào, làm phần độc lập, rồi nhận completion/blocker để mở phần
phụ thuộc. Không polling trạng thái hay sleep-retry; nếu hết việc độc lập thì dùng
một event wait/yield. Timeout không tự cho phép vòng chờ mới.

Hồ sơ gói ở `workspace/agents/<package>/<role>/`, handoff khoảng 40 dòng: source,
đầu ra, file/nodes/edges đổi, check thực chạy, đường dẫn bằng chứng, claim cao nhất,
blocker và bước tiếp. ROOT lưu báo cáo của role chỉ đọc khi cần. Không tạo bản
v1/v2/final hoặc trạng thái điều phối song song; sửa [ROOT](ROOT.md) tại chỗ.

ROOT so bằng chứng với acceptance và commit, chạy kiểm tập trung khi có lý do,
rồi ghi rõ agent báo, ROOT đã xác minh, và phần chưa biết. Test offline chỉ chứng
minh code/contract được test; không tự nâng lên WIRED, live, REPEATABLE hay STABLE.
Không sửa dữ liệu đo gốc, xoá archive hoặc biến kế hoạch thành bằng chứng.

Cấu hình đội không tự cho phép capture/input, mission tick, gọi endpoint model,
thay model server, thao tác tài khoản, gửi tin, publish hay thanh toán. Một lần
live cần quyền công việc GATHER của người vận hành và các chốt được chứng minh
theo đúng job/occurrence. [SESSION_AUTHORITY](SESSION_AUTHORITY.md) định nghĩa
quyền khởi đầu cho FIRST DONE; B003 từng occurrence là đường benchmark lịch sử,
không phải yêu cầu duyệt từng march. Mức chứng minh của từng gói chỉ lấy từ
[runtime-status](../runtime-status.yaml) và bằng chứng ROOT đã kiểm.
