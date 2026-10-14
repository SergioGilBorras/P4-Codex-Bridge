# Instrucciones para documentación

- Mantén documentación factual, concisa y con enlaces relativos válidos.
- `CAPABILITY_MATRIX.md` explica la evidencia de capacidades; `MCP.md` y `SKILLS.md` describen la consulta de herramientas y skills sin inventarios de una sesión. No dupliques los catálogos de features ni de tests.
- El entorno cambia: no guardes snapshots de herramientas de una sesión como garantías permanentes. Distingue observaciones del host y pruebas asociadas al run.
- **Tool discovery is part of the task. Antes de resolver manualmente un problema complejo, comprueba si Serena, PyCharm, una skill o un MCP disponible proporciona una operación especializada para ello.**
- **Use the cheapest reliable source of truth.** Prefiere la consulta estructurada o específica más pequeña que responda a la pregunta.
- No documentes nombres o capacidades inferidos; comprueba el catálogo de tools y la descripción de la skill.

- Presenta únicamente funciones implementadas, limitaciones vigentes y el roadmap; evita narrativas de fases, recuentos de tests obsoletos e inventarios de una sesión anterior en páginas activas.
- Conserva referencias versionadas de contratos por compatibilidad, pero no las utilices como descripción de la API actual.

- Este repositorio está en pruebas internas sin clientes externos; describe solo contratos vigentes y el roadmap. No mantengas documentación de APIs obsoletas, fases anteriores, ADRs retiradas o migraciones sin una necesidad explícita.
