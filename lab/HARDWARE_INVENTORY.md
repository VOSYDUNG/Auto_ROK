# Kiểm kê phần cứng

Đo ngày **2026-09-20** trên chính máy đang chạy dự án. Mọi số đều lấy từ hệ thống, không
chép từ tài liệu nhà sản xuất.

## Máy đang chạy dự án

| | |
|---|---|
| Bo mạch | Intel X99 (desktop/workstation) |
| CPU | Intel Xeon E5-2686 v4 @ 2.30 GHz |
| Nhân / luồng | **18 / 36** |
| L3 cache | **45 MB** |
| RAM | **64 GB** |
| GPU | AMD Radeon R5 430, 2 GB |
| CUDA | **không có** — `nvidia-smi` không tồn tại |

**Đây không phải Dell Precision 7520.** Người vận hành nhắc tới Quadro M1200 MXM của một
laptop 7520; card đó **không nằm trong máy này**.

### Xeon này mạnh hơn tưởng

E5-2686 v4 là Broadwell-EP. Vài điểm đáng chú ý cho suy luận LLM:

- **36 luồng** — llama.cpp chạy CPU co giãn tốt theo số luồng tới một ngưỡng
- **45 MB L3** — rất lớn, giúp ích cho suy luận theo lô
- **64 GB RAM** — model 11,3 GB nằm **trọn trong RAM**, không phải đọc đĩa
- **Có AVX2, KHÔNG có AVX-512** — Broadwell chưa có AVX-512. Bản build nào quảng cáo tăng
  tốc AVX-512 đều vô dụng ở đây

## Runtime LLM đã cài

| | |
|---|---|
| llama.cpp | build **10901**, commit `28ff09582`, version `0.4.0-dev` |
| Nguồn | WinGet, gói `ggml.llamacpp` |
| Biên dịch | Clang 20.1.8, **x86_64 — bản CPU**, không thấy dấu hiệu CUDA |
| Nhị phân | `llama-server.exe`, `llama-cli.exe` |

## Model có sẵn

| Model | Kích thước | Ghi chú |
|---|---|---|
| `gpt-oss-20b-MXFP4.gguf` | **11,3 GB** | model đang cấu hình trong `config/local-llm.json` |
| `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf` | **17,3 GB** | phương án thay thế đã khai trong config |

Cả hai **vừa RAM 64 GB**, không vừa VRAM 4 GB.

## Số đo hiệu năng đã có

Từ bằng chứng dự án, không phải đo lại trong lab:

| Hạng mục | Số đo | Nguồn |
|---|---|---|
| Một quyết định LLM (tầng chiến thuật) | **20,6 s** trung vị · 29,0 s p95 | `workspace/evidence/local_llm/` |
| Cùng thế với trần 512 token | 44,0 s | thử nghiệm 2026-09-19 |
| Một khung OCR qua `windows_ocr.ps1` | **4.863 ms** | đo 2026-09-20 trên khung game thật |
| Đọc hàng đợi bằng template | **0,207 ms** | `harness/queue_indicator.py` |
| Phát input `SendInput` | **< 1 ms** | đo 2026-09-19 |

## Chưa đo — và đây là chỗ nên bắt đầu

| Cần đo | Vì sao chưa có |
|---|---|
| tokens/giây thật của `llama-server` | chưa chạy benchmark, cổng 8080 đang đóng |
| số luồng `llama-server` đang thực dùng | chưa kiểm tham số `-t` |
| thời gian nạp model vs thời gian sinh token | 20,6 s là tổng, chưa tách |
| bản WinGet có bật AVX2 không | chưa kiểm |

**Bốn dòng trên đều miễn phí và có thể làm ngay.** Không nên bàn tới phần cứng trước khi
có chúng — có khả năng 20,6 s phần lớn là cấu hình sai chứ không phải CPU yếu.
