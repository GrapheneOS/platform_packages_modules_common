# This set of Proguard rules is intended for any module java_sdk_library
# target. It is intentionally more conservative than the default global
# Proguard configuration, as library targets, particularly updatable
# targets, must preserve certain levels of compatiblity across the API
# boundary for stable interop with downstream targets.

# A minimal set of attributes necessary to preserve public API signature
# stability across releases, particularly for generic types that might be
# referenced via reflection. See also Cts*ApiSignatureTestCases.
-keepattributes EnclosingMethod,InnerClasses,Signature
