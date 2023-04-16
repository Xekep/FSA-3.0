import turtle

# Создание экрана
screen = turtle.Screen()
screen.title("Пример круговой диаграммы с индикатором прогресса")

# Создание черепахи
t = turtle.Turtle()

# Определение данных для круговой диаграммы
data = {"А": 30, "Б": 20, "В": 50}

# Определение цветов для каждого сектора
colors = ["red", "green", "blue"]

# Начальный угол для первого сектора
start_angle = 0

# Отрисовка круговой диаграммы
for label, value in data.items():
    # Рассчет угла для текущего сектора
    angle = value / sum(data.values()) * 360

    # Заполнение сектора цветом и отрисовка его границы
    t.fillcolor(colors.pop(0))
    t.begin_fill()
    t.goto(0, 0)
    t.setheading(start_angle)
    t.circle(100, angle)
    t.goto(0, 0)
    t.end_fill()

    # Обновление угла для следующего сектора
    start_angle += angle

    # Отрисовка индикатора прогресса
    t.penup()
    t.setheading(start_angle - angle/2)
    t.forward(80)
    t.write(f"{value}%", align="center", font=("Arial", 10, "normal"))
    t.back(80)
    t.pendown()

# Скрытие черепахи
t.hideturtle()

# Запуск главного цикла приложения
turtle.mainloop()
