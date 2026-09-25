"""F1 / ROC / PR 엑셀 템플릿 생성기.

eval_dcase.csv 를 'data' 시트에 붙여넣으면 threshold 스윕 -> F1/ROC/PR 차트가
자동 갱신되는 .xlsx 를 만든다. (pandas/openpyxl 없이 xlsxwriter 만 사용)

수식은 plot_metrics.py 와 동일한 표준 정의:
  pred(t)=score>=t,  P=TP/(TP+FP),  R=TP/(TP+FN),  F1=2PR/(P+R)
  TPR=R,  FPR=FP/(FP+TN),  AUC=사다리꼴 적분
"""

import xlsxwriter

OUT = "metrics_template.xlsx"

# data 시트 미리보기용 예시 데이터(붙여넣으면 덮어쓰기) — 실제 CSV 일부
SAMPLE = [
    [23890,1,1,0.225253,0.882694,0.658685,1],
    [24247,1,1,1.268925,1.929762,0.659448,1],
    [26765,1,1,-2.944334,-1.604411,0.792477,1],
    [25189,1,1,0.413338,0.850609,0.607608,1],
    [11601,0,0,1.978862,0.921897,0.257890,1],
    [1117,0,1,0.079063,0.488701,0.601001,0],
    [1756,0,0,-1.033649,-2.460118,0.193649,1],
    [16881,1,1,-0.482381,0.174933,0.658657,1],
    [6751,0,1,-0.449343,-0.194836,0.563285,0],
    [870,0,1,-0.599104,0.287925,0.708277,0],
    [19741,1,1,0.371475,0.468781,0.524307,1],
    [9104,0,0,1.402748,1.318389,0.478923,1],
    [721,0,1,0.127814,1.098003,0.725157,0],
    [10997,0,0,1.490009,0.817311,0.337893,1],
    [17270,1,1,0.017394,0.589315,0.639206,1],
    [19727,1,1,-0.268864,-0.203573,0.516317,1],
    [25292,1,1,1.046037,1.679928,0.653371,1],
    [26897,1,1,-0.153106,0.075816,0.556982,1],
    [8347,0,0,1.085020,0.973325,0.472105,1],
    [15588,1,1,-1.182490,0.011487,0.767452,1],
    [27520,1,1,-0.775820,0.831219,0.833000,1],
    [10938,0,0,0.535450,0.194744,0.415638,1],
    [24386,1,1,0.764060,1.222285,0.612593,1],
    [24480,1,1,0.782524,1.098141,0.578256,1],
    [314,0,1,-0.290220,-0.176867,0.528308,0],
    [27907,1,1,0.161860,0.876648,0.671458,1],
    [24357,1,1,-0.457157,0.380906,0.698057,1],
    [25524,1,1,0.061096,0.816642,0.680386,1],
    [20588,1,1,-0.778284,0.040099,0.693893,1],
    [5850,0,0,-2.300770,-4.145677,0.136472,1],
]

wb = xlsxwriter.Workbook(OUT)
hdr = wb.add_format({"bold": True, "bg_color": "#DDEBF7", "border": 1})
note = wb.add_format({"italic": True, "font_color": "#C00000", "text_wrap": True})
f4 = wb.add_format({"num_format": "0.0000"})
klbl = wb.add_format({"bold": True})

# data 시트
ws = wb.add_worksheet("data")
cols = ["seg_index", "true_label", "pred_label", "mem_normal",
        "mem_anomaly", "score_anomaly", "correct"]
for c, h in enumerate(cols):
    ws.write(0, c, h, hdr)
for r, row in enumerate(SAMPLE, start=1):
    ws.write_row(r, 0, row)
ws.set_column(0, 6, 12)
ws.write(0, 9, "▶ 사용법: 이 시트 A1(또는 A2)부터 eval_dcase.csv 전체를 붙여넣으면 "
               "metrics 시트 차트가 자동 갱신됩니다. 위 예시 행은 덮어쓰세요. "
               "(true_label=B열, score_anomaly=F열 / 값이 숫자여야 함)", note)
ws.set_column(9, 9, 60)

# metrics 시트
ms = wb.add_worksheet("metrics")
mcols = ["threshold", "TP", "FP", "FN", "TN", "Precision", "Recall(TPR)", "F1", "FPR"]
for c, h in enumerate(mcols):
    ms.write(0, c, h, hdr)

TRUE = "data!$B$2:$B$100000"   # true_label
SCOR = "data!$F$2:$F$100000"   # score_anomaly

for i in range(101):                 # threshold 0.00 ~ 1.00
    r = i + 1                        # 0-based 시트 행 (1..101)
    er = r + 1                       # 1-based 엑셀 행 (2..102)
    ms.write_number(r, 0, i / 100.0, f4)
    A = f"$A{er}"
    ms.write_formula(r, 1, f'=COUNTIFS({TRUE},1,{SCOR},">="&{A})')   # TP
    ms.write_formula(r, 2, f'=COUNTIFS({TRUE},0,{SCOR},">="&{A})')   # FP
    ms.write_formula(r, 3, f'=COUNTIFS({TRUE},1,{SCOR},"<"&{A})')    # FN
    ms.write_formula(r, 4, f'=COUNTIFS({TRUE},0,{SCOR},"<"&{A})')    # TN
    TP, FP, FN, TN = f"$B{er}", f"$C{er}", f"$D{er}", f"$E{er}"
    P, R = f"$F{er}", f"$G{er}"
    ms.write_formula(r, 5, f"=IF(({TP}+{FP})=0,0,{TP}/({TP}+{FP}))", f4)   # Precision
    ms.write_formula(r, 6, f"=IF(({TP}+{FN})=0,0,{TP}/({TP}+{FN}))", f4)   # Recall=TPR
    ms.write_formula(r, 7, f"=IF(({P}+{R})=0,0,2*{P}*{R}/({P}+{R}))", f4)  # F1
    ms.write_formula(r, 8, f"=IF(({FP}+{TN})=0,0,{FP}/({FP}+{TN}))", f4)   # FPR
ms.set_column(0, 8, 11)

# 요약
ms.write(0, 10, "요약", klbl)
ms.write(1, 10, "best F1", klbl);          ms.write_formula(1, 11, "=MAX($H$2:$H$102)", f4)
ms.write(2, 10, "best threshold", klbl);   ms.write_formula(2, 11, "=INDEX($A$2:$A$102,MATCH(MAX($H$2:$H$102),$H$2:$H$102,0))", f4)
ms.write(3, 10, "F1 @0.5 (argmax)", klbl); ms.write_formula(3, 11, "=$H$52", f4)
ms.write(4, 10, "ROC AUC", klbl);          ms.write_formula(4, 11, "=SUMPRODUCT(($I$2:$I$101-$I$3:$I$102),($G$2:$G$101+$G$3:$G$102)/2)", f4)
ms.write(5, 10, "PR AUC", klbl);           ms.write_formula(5, 11, "=SUMPRODUCT(($G$2:$G$101-$G$3:$G$102),($F$2:$F$101+$F$3:$F$102)/2)", f4)
ms.set_column(10, 11, 16)

# 차트
c_f1 = wb.add_chart({"type": "line"})
c_f1.add_series({"name": "F1",
                 "categories": "=metrics!$A$2:$A$102",
                 "values": "=metrics!$H$2:$H$102",
                 "line": {"color": "#ED7D31"}})
c_f1.set_title({"name": "F1 vs Threshold"})
c_f1.set_x_axis({"name": "threshold", "min": 0, "max": 1})
c_f1.set_y_axis({"name": "F1", "min": 0, "max": 1})
c_f1.set_legend({"none": True})
ms.insert_chart("K8", c_f1)

c_roc = wb.add_chart({"type": "scatter", "subtype": "straight"})
c_roc.add_series({"name": "ROC",
                  "categories": "=metrics!$I$2:$I$102",   # FPR = X
                  "values": "=metrics!$G$2:$G$102",        # TPR = Y
                  "line": {"color": "#4472C4"}})
c_roc.set_title({"name": "ROC Curve"})
c_roc.set_x_axis({"name": "FPR", "min": 0, "max": 1})
c_roc.set_y_axis({"name": "TPR", "min": 0, "max": 1})
c_roc.set_legend({"none": True})
ms.insert_chart("K24", c_roc)

c_pr = wb.add_chart({"type": "scatter", "subtype": "straight"})
c_pr.add_series({"name": "PR",
                 "categories": "=metrics!$G$2:$G$102",     # Recall = X
                 "values": "=metrics!$F$2:$F$102",          # Precision = Y
                 "line": {"color": "#7030A0"}})
c_pr.set_title({"name": "Precision-Recall"})
c_pr.set_x_axis({"name": "Recall", "min": 0, "max": 1})
c_pr.set_y_axis({"name": "Precision", "min": 0, "max": 1})
c_pr.set_legend({"none": True})
ms.insert_chart("K40", c_pr)

wb.close()
print(f"saved: {OUT}")
