# Vận hành đội agent Auto_ROK

[ROOT](ROOT.md) chọn một đầu ra đang thiếu; [BUILD_PLAN](BUILD_PLAN.md) giữ thứ tự
phụ thuộc, [runtime-status](../runtime-status.yaml) giữ kết quả đã chứng minh.
Phương thức được chỉnh từ audit 2026-10-03, không cấp thêm quyền gameplay.

## Chọn đội theo việc

Model ROOT do người dùng chọn trong phiên. Trước mỗi gói, ROOT chọn
**vai trò × model × effort × context × autonomy** từ tool thực có và chỉ định
của người dùng; ghi lựa chọn vào brief gói, không ghim model trong chính sách
repo hoặc đổi mặc định toàn máy. Có tên model trong menu không chứng minh quota.
Model chỉ định không chạy được thì báo blocker; không thay bằng model bị loại trừ.
ROOT có thể làm phần độc lập bằng model hiện hành theo fallback đã có.

[team.json](../.codex/team.json) giới hạn tối đa hai child, không vượt slot host.
Người nghiên cứu làm rõ giả định; builder sửa một phạm vi nối được; tester kiểm
đầu ra; reviewer kiểm thay đổi authority/proof/recovery hoặc rủi ro đáng kể.
Không gọi đủ ghế theo nghi thức. Một lỗi nhỏ đã có source/reproducer thì ROOT
sửa trực tiếp; chỉ tách agent khi có phần độc lập có ích.

Writer có file/node sở hữu rời nhau. Reviewer chỉ đọc và trả kết quả để ROOT
lưu; child không sửa orchestration state, commit/push hoặc tự mở child.

## Nhịp coding để giao được một chu kỳ

Một gói runtime đang hoạt động trên đường FIRST DONE; phần độc lập có thể
chạy song song. Đơn vị giao hàng là **chu kỳ nghiệp vụ**, không phải mỗi nút,
mỗi detector hoặc số test/commit. Không mở lại nhân vật, tỷ lệ, cặp game tự
điền hay quyền từng March khi người dùng đã chốt và scope chưa đổi.

1. Đọc ROOT và source slice của blocker; không nạp lại toàn bộ hồ sơ cũ.
2. Tái hiện lỗi rẻ nhất từ artifact/code trước khi sửa. Chỉ ra bước trước,
   bước bị chặn, consumer và postcondition cần đạt; phân biệt thực đo/suy luận.
3. Sửa canonical path nhỏ nhất và nối luôn test consumer. Test route phải bắt
   đầu từ trạng thái đầu thực tế, không chỉ dựng sẵn COMPLETE hoặc New Troop.
4. Kiểm focused sau patch; kiểm tích hợp tại biên gói. Một bộ rộng cho checkpoint
   thay đổi nhiều phần hoặc publication khi cần; không chạy lại vì đổi câu chữ.
   Giữ failure; rerun chỉ khi sửa, có lỗi mới hoặc cần chẩn đoán riêng có câu hỏi.
5. Review độc lập theo rủi ro, rồi ROOT kiểm bằng chứng và tích hợp một lần.
   Thiếu asset/wiring không được nhận WIRED; test tổng hợp không thành live.
6. Đóng gói đủ code/profile/assets rồi ghim nguồn trước live. Một driver chạy
   cả job; không mở cuộc hội ý hoặc giao agent giữa các click đã rõ.
7. Khi driver dừng, lưu cause và fact mới. Nếu cần sửa/calibration/UI hỗ trợ,
   dừng nghiệm thu tự chủ của occurrence; sửa offline rồi cấp job mới phù hợp.
   Không replay March mơ hồ, nối quota hoặc nâng vòng có hỗ trợ thành tự chủ.

Gói ghi giới hạn thử/effort phù hợp. Hai lần cùng hướng thất bại mà không có
bằng chứng mới phải đổi giả thuyết hoặc cách tiếp cận; không tiếp tục mò bằng
cùng thao tác. Đây là trigger xem lại phương pháp, không tự tạo retry hoặc deadline.
Đo time-to-first-March, whole-job time, can thiệp và tỷ lệ trọn vòng trên cùng
ranh giới; chưa có baseline thì ghi unknown, không hứa nhanh hơn script.

## Brief và kiểm chứng

Mỗi brief tự đủ: mục tiêu/lý do, commit/source, `owned_nodes`,
`upstream_dependencies`, `downstream_consumers`, `acceptance_evidence`,
`known_blockers`, `graph_delta_expected`, file sở hữu/loại trừ,
model/effort/context/autonomy, giới hạn thử và side effect. Các field này phục
vụ đúng gói, không biến thành thêm một hệ gate hoặc tài liệu tiến độ.

Khởi chạy agent khi đủ đầu vào, ROOT làm phần độc lập và nhận completion/blocker.
Không polling/list/read loop/sleep-retry. Nếu hết phần độc lập, dùng một event
wait/yield; timeout không mở vòng chờ mới. Không tạo task sidebar thay child.

Hồ sơ ở `workspace/agents/<package>/<role>/`; handoff khoảng 40 dòng nêu node,
edge/file đổi, checks thực chạy, evidence, claim cao nhất, blocker và consumer.
ROOT kiểm scope/source/acceptance rồi viết lại ROOT tại chỗ. Không cộng các
suite chồng nhau hoặc lấy số test tăng làm tiến độ sản phẩm. Lưu elapsed/tách
setup, OCR, capture, input, verification khi tối ưu, không trộn boundary đo.

## Tài liệu và quyền

AGENTS/team/role files sở hữu phương thức và giới hạn đội; AGENT_OPERATIONS
sở hữu nhịp coding. PRD sở hữu nghiệm thu; SRS là chi tiết kỹ thuật; GOAL và
PROJECT_DECLARATION giữ mục tiêu/biên. Graph giữ dependency/authority, không
chứa claim live. BUILD_PLAN chỉ giữ việc còn lại; lịch sử ở Git/workspace.
ROOT chỉ giữ quyết định, evidence index và gói kế tiếp. Audit/coverage/reference
có ngày không được ghi đè lên nguồn hiện hành; không tạo v1/v2/final.

[SESSION_AUTHORITY](SESSION_AUTHORITY.md) sở hữu quyền job và hỗ trợ ROOT.
Cấu hình đội không cấp capture/input/model endpoint/server/account action,
publish hay thanh toán. Dùng quyền người dùng đã cấp đúng scope; kiểm focus,
frame, client, quota trước hành động là guard kỹ thuật. B003/R3 là benchmark
lịch sử riêng, không phải duyệt mỗi March của FIRST DONE. Local LLM chỉ nhận
bất định có nghĩa; không thêm model call cho một bước xác định.
