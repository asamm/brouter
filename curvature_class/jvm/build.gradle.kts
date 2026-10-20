plugins {
    kotlin("jvm") version "2.2.20"
    // JSON in/out (out/roads.json -> out/roads_cost.json)
    kotlin("plugin.serialization") version "2.2.20"
}

repositories {
    mavenCentral()
}

dependencies {
    // version is ignored, the composite build substitutes the projects from ../..
    testImplementation("org.btools:brouter-core:1.7.8")
    testImplementation("org.btools:brouter-mapaccess:1.7.8")
    testImplementation("org.btools:brouter-expressions:1.7.8")
    testImplementation("org.btools:brouter-util:1.7.8")
    testImplementation("org.btools:brouter-codec:1.7.8")
    testImplementation(kotlin("test"))
    testImplementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
}

tasks.test {
    useJUnitPlatform()
    testLogging {
        events("passed", "failed", "skipped")
        showStandardStreams = true
    }
}
