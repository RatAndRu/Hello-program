Папка для моделей MediaPipe (*.task).

Сюда приложение складывает два файла, которые скачивает один раз при первом
запуске (около 8 МБ суммарно):

  hand_landmarker.task  — 21 точка кисти
  face_landmarker.task  — 468 точек лица

Скачать вручную (если нет интернета на машине с камерой):

  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task

Или одной командой:  python -m airmouse models

Если файлов нет и скачать не получается, приложение автоматически перейдёт на
классический бэкенд (--backend classical) — он работает без моделей, но грубее
и без мимики.
