# Мост JS → Kotlin (сохранение и «поделиться»): методы вызываются из JavaScript по имени.
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
-keep class com.example.obyom.MainActivity$NativeBridge { *; }
-keepattributes JavascriptInterface
