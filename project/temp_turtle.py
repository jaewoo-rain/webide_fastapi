# -*- coding: utf-8 -*-
import matplotlib.pyplot as plt

# ���� ������
x = [1, 2, 3, 4, 5]
y = [1, 4, 9, 16, 25]

# �׷��� �׸���
plt.plot(x, y)
plt.title("Sample Line Plot")
plt.xlabel("X Axis")
plt.ylabel("Y Axis")

# �׸��� ǥ�� (����)
plt.grid(True, linestyle="--", linewidth=0.5)

# ȭ�鿡 ���
plt.show()
