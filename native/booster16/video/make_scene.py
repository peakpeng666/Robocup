#!/usr/bin/env python3
"""Create single-robot observer scene, referencing unmodified pinned assets."""
import pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
out = pathlib.Path(sys.argv[2]).resolve()
inc = root / 'Config/Scenes/Includes'
out.parent.mkdir(parents=True, exist_ok=True)
assert not out.exists(), 'Preserve previous scene evidence'
out.write_text(f'''<Simulation>
  <Include href="{inc}/BallFifa3.rsi3"/>
  <Include href="{inc}/Field2026HSLM.rsi3"/>
  <Include href="{inc}/K1/K1.rsi3"/>
  <Scene name="RoboCup" controller="SoccerVideoObserver" stepLength="0.002" color="rgb(65%, 65%, 70%)">
    <PointLight z="9m" intensity="8"/>
    <Compound name="teams">
      <Compound name="B-Human"><Compound name="5"/><Compound name="white"/><Compound name="purple"/></Compound>
      <Compound name="B-Team"><Compound name="70"/><Compound name="red"/><Compound name="blue"/></Compound>
    </Compound>
    <Compound name="robots">
      <Body ref="K1" name="robot5">
        <Set name="TeamColor" value="skin"/>
        <Translation x="1m" z="0.537m"/>
        <Rotation z="180degree"/>
      </Body>
    </Compound>
    <Compound name="extras"/>
    <Compound name="balls"><Body ref="ball"><Translation x="0m" z="0.10m"/></Body></Compound>
    <Compound ref="field"/>
    <Compound name="location"><Compound name="MField"/></Compound>
    <Compound ref="robot type"/>
    <Compound name="Observer">
      <Camera name="Camera" imageWidth="960" imageHeight="540" angleX="75degree" angleY="46.69degree">
        <Translation x="-2m" y="-5.5m" z="3.7m"/>
        <Rotation y="29degree" z="70degree"/>
      </Camera>
    </Compound>
  </Scene>
</Simulation>
''')
out.with_suffix('.con').write_text(f'''call {inc}/Normal
ar directGoals on
gc playing
''')
print(out)
