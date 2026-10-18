# Мост JS → Kotlin (сохранение и «поделиться»): методы вызываются из JavaScript по имени.
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
-keep class com.example.reyka.MainActivity$NativeBridge { *; }
-keepattributes JavascriptInterface
