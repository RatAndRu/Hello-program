package com.example.pinphotoswidget

import android.content.Context
import android.graphics.Matrix
import android.graphics.PointF
import android.util.AttributeSet
import android.view.GestureDetector
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.widget.ImageView
import kotlin.math.min

/** Просмотр фото с зумом щипком, перемещением и двойным тапом. */
class ZoomImageView @JvmOverloads constructor(
    context: Context, attrs: AttributeSet? = null
) : ImageView(context, attrs) {
    private var baseMatrix = Matrix()
    private var drawMatrix2 = Matrix()
    private var scaleFactor = 1f
    private var lastFocus = PointF()
    private var mode = 0 // 0 none, 1 drag

    private val scaleDetector = ScaleGestureDetector(context, object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
        override fun onScale(detector: ScaleGestureDetector): Boolean {
            val old = scaleFactor
            scaleFactor = (scaleFactor * detector.scaleFactor).coerceIn(1f, 5f)
            val real = scaleFactor / old
            drawMatrix2.postScale(real, real, detector.focusX, detector.focusY)
            clamp(); imageMatrix = drawMatrix2
            return true
        }
    })
    private val gestureDetector = GestureDetector(context, object : GestureDetector.SimpleOnGestureListener() {
        override fun onDoubleTap(e: MotionEvent): Boolean {
            if (scaleFactor > 1.05f) reset() else {
                drawMatrix2.postScale(2.2f, 2.2f, e.x, e.y); scaleFactor = 2.2f; clamp(); imageMatrix = drawMatrix2
            }
            return true
        }
    })

    init { scaleType = ScaleType.MATRIX; isClickable = true }

    override fun setImageBitmap(bm: android.graphics.Bitmap?) {
        super.setImageBitmap(bm); post { fitBase(); reset() }
    }

    private fun fitBase() {
        val d = drawable ?: return
        baseMatrix.reset()
        val viewW = width - paddingLeft - paddingRight
        val viewH = height - paddingTop - paddingBottom
        if (viewW <= 0 || viewH <= 0 || d.intrinsicWidth <= 0) return
        val scale = min(viewW.toFloat() / d.intrinsicWidth, viewH.toFloat() / d.intrinsicHeight)
        baseMatrix.setScale(scale, scale)
        baseMatrix.postTranslate((viewW - d.intrinsicWidth * scale) / 2f + paddingLeft,
            (viewH - d.intrinsicHeight * scale) / 2f + paddingTop)
    }

    private fun reset() { drawMatrix2.set(baseMatrix); scaleFactor = 1f; imageMatrix = drawMatrix2 }

    private fun clamp() {
        // Лёгкая фиксация, чтобы картинка не уезжала бесконечно за экран
        val values = FloatArray(9); drawMatrix2.getValues(values)
        val maxShift = 600f
        values[Matrix.MTRANS_X] = values[Matrix.MTRANS_X].coerceIn(-maxShift * scaleFactor, maxShift * scaleFactor)
        values[Matrix.MTRANS_Y] = values[Matrix.MTRANS_Y].coerceIn(-maxShift * scaleFactor, maxShift * scaleFactor)
        drawMatrix2.setValues(values)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        scaleDetector.onTouchEvent(event); gestureDetector.onTouchEvent(event)
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> { mode = 1; lastFocus.set(event.x, event.y) }
            MotionEvent.ACTION_POINTER_DOWN -> mode = 0
            MotionEvent.ACTION_MOVE -> if (mode == 1 && scaleFactor > 1f && event.pointerCount == 1) {
                drawMatrix2.postTranslate(event.x - lastFocus.x, event.y - lastFocus.y)
                lastFocus.set(event.x, event.y); clamp(); imageMatrix = drawMatrix2
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> mode = 0
        }
        parent?.requestDisallowInterceptTouchEvent(scaleFactor > 1f)
        return true
    }
}
