# -*- coding: utf-8 -*-
import matplotlib.pyplot as plt

# 예시 데이터
x = [1, 2, 3, 4, 5]
y = [1, 4, 9, 16, 25]

# 그래프 그리기
plt.plot(x, y)
plt.title("Sample Line Plot")
plt.xlabel("X Axis")
plt.ylabel("Y Axis")

# 그리드 표시 (선택)
plt.grid(True, linestyle="--", linewidth=0.5)

# 화면에 출력
plt.show()
