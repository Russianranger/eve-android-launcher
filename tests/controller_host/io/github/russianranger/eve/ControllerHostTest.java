package io.github.russianranger.eve;

import java.util.*;

/** Verifies controller behavior without Android, a socket, or a running game. */
public final class ControllerHostTest {
    private static int assertions;
    private static void check(boolean condition,String message){assertions++;if(!condition)throw new AssertionError(message);}
    private static final class Recorder implements ControllerInput.Sink {
        final List<String> events=new ArrayList<>(),layers=new ArrayList<>();
        final Set<String> down=new HashSet<>();
        float x,y;int wheels,menus;
        public void button(String action,boolean pressed){
            if(action.equals("ClientMenu")){check(pressed,"Menu action is one-shot");menus++;return;}
            check(pressed?down.add(action):down.remove(action),"No duplicate down or unmatched release: "+action+":"+pressed);
            events.add(action+":"+pressed);
        }
        public void pointer(float dx,float dy){check(Float.isFinite(dx)&&Float.isFinite(dy),"Motion stays finite");x+=dx;y+=dy;}
        public void wheel(int amount){wheels+=amount;}
        public void layer(int index,String name){layers.add(index+":"+name);}
    }
    private static void defaultsAndCycle(){
        List<ControllerInput.Layer> layers=ControllerInput.defaultLayers();Map<String,String> expected=new LinkedHashMap<>();
        String[] sources={"A","X","Y","B","R1","L1","L2","R2","DpadUp","DpadRight","DpadDown","DpadLeft","Select","Start","L3","R3","LeftUp","LeftDown","LeftLeft","LeftRight","RightUp","RightDown","RightLeft","RightRight"};
        String[] actions={"KeyF","Digit1","Digit2","Digit3","MouseLeft","MouseRight","LayerNext","Tab","Digit4","Digit5","Digit6","Digit7","Escape","KeyI","Home","KeyC","KeyW","KeyS","KeyA","KeyD","PointerUp","PointerDown","PointerLeft","PointerRight"};
        for(int i=0;i<sources.length;i++)expected.put(sources[i],actions[i]);
        check(layers.get(0).bindings.equals(expected),"Main exactly matches the established TRASC Thor profile");
        check(layers.size()==4&&layers.get(1).name.equals("Hotbar 2")&&layers.get(2).name.equals("Spells")&&layers.get(3).name.equals("Inventory"),"Four established named layers");
        Recorder out=new Recorder();ControllerInput input=new ControllerInput(out);input.configure(layers,.2f,700);input.activate(true);
        input.value("X",1);input.value("L2",1);input.value("L2",1);input.value("L2",.6f);
        check(input.currentLayer()==1,"Repeated and analog down cycles only once");
        check(out.events.equals(Arrays.asList("Digit1:true","Digit1:false","Digit8:true")),"Layer releases old binding before reapplying held source");
        input.value("L2",0);input.value("X",0);check(input.currentLayer()==1,"Cycle selection persists after trigger release");
        for(int i=0;i<3;i++){input.value("L2",1);input.value("L2",0);}check(input.currentLayer()==0,"Four-layer cycle wraps");
        input.nextLayer();check(input.currentLayer()==1,"Gear can advance layer");input.selectLayer(3);check(input.layerName().equals("Inventory"),"Gear can select layer");
        input.activate(false);check(out.down.isEmpty(),"Deactivation releases all gameplay input");
        check(input.currentLayer()==3,"Menu and focus transitions retain selected persistent layer");
    }
    private static void heldLayersAndChords(){
        Recorder out=new Recorder();ControllerInput input=new ControllerInput(out);List<ControllerInput.Layer> layers=new ArrayList<>(ControllerInput.defaultLayers());
        Map<String,String> main=new LinkedHashMap<>(layers.get(0).bindings);
        main.put("L1","HoldLayer3");main.put("R1","HoldLayer4");main.put("R2","LayerPrevious");main.put("Select","Layer2");
        layers.set(0,new ControllerInput.Layer("Main",main));input.configure(layers,.2f,700);input.activate(true);
        input.value("R2",1);input.value("R2",0);check(input.currentLayer()==3,"Previous wraps backward");
        input.value("Select",1);input.value("Select",0);check(input.currentLayer()==1,"Direct target selects named layer");
        input.value("L1",1);check(input.currentLayer()==2,"Held layer overrides selected layer");input.value("R1",1);check(input.currentLayer()==3,"Latest held layer wins");
        input.value("R1",0);check(input.currentLayer()==2,"Nested hold release restores prior hold");input.value("L1",0);check(input.currentLayer()==1,"Final hold release restores persistent selection");
        input.value("L1",1);input.value("X",1);input.activate(false);
        check(input.currentLayer()==1&&out.down.isEmpty(),"Focus loss clears chord and temporary layer");
        out.events.clear();main=ControllerInput.defaults();main.put("A","AltLeft+Digit1");main.put("B","AltLeft+Digit2");
        input.configure(main,.2f,700);input.activate(true);input.value("A",1);input.value("B",1);
        check(out.events.subList(0,2).equals(Arrays.asList("AltLeft:true","Digit1:true")),"Chord presses modifier first");
        input.value("A",0);check(out.down.contains("AltLeft")&&!out.down.contains("Digit1"),"Overlapping chords retain common modifier");
        input.value("B",0);check(out.events.get(out.events.size()-1).equals("AltLeft:false")&&out.down.isEmpty(),"Final chord releases modifier last");
    }
    private static void referenceCountsAndOneShots(){
        Recorder out=new Recorder();ControllerInput input=new ControllerInput(out);Map<String,String> bindings=ControllerInput.defaults();
        bindings.put("A","KeyW");bindings.put("B","MouseLeft");bindings.put("R1","MouseLeft");bindings.put("Y","ClientMenu");
        List<ControllerInput.Layer> configured=new ArrayList<>(ControllerInput.defaultLayers());configured.set(0,new ControllerInput.Layer("Main",bindings));input.configure(configured,.2f,700);input.activate(true);input.value("A",1);input.axis("LeftUp","LeftDown",-1);
        input.value("A",0);check(out.down.contains("KeyW"),"Stick holds same key after button releases");
        input.axis("LeftUp","LeftDown",0);check(!out.down.contains("KeyW"),"Final source releases shared key");
        input.value("B",1);input.value("R1",1);input.value("B",0);check(out.down.contains("MouseLeft"),"Mouse holds are also reference counted");
        input.value("R1",0);check(out.down.isEmpty(),"Final mouse source releases");
        input.value("Y",1);input.value("Y",1);input.value("Y",0);check(out.menus==1,"Menu repeats are guarded");
        input.selectLayer(3);input.value("DpadUp",1);input.value("DpadUp",1);input.value("DpadUp",0);check(out.wheels==1,"Wheel repeat produces exactly one upward pulse");
        input.value("DpadDown",1);input.value("DpadDown",0);check(out.wheels==0,"Inventory wheel sends one pulse per direction press");
        input.value("R2",1);input.value("R2",.8f);input.value("R2",1);input.value("R2",.1f);
        check(!out.down.contains("Tab"),"Changing held trigger magnitude does not add duplicate keys");
        input.releaseAll();input.releaseAll();check(out.down.isEmpty(),"Release-all is idempotent");
    }
    private static void analogMotion(){
        Recorder out=new Recorder();ControllerInput input=new ControllerInput(out);input.configure(ControllerInput.defaultLayers(),.2f,700);input.activate(true);
        input.axis("RightLeft","RightRight",.2f);input.tick(.016f);check(out.x==0,"Deadzone suppresses drift");
        input.axis("RightLeft","RightRight",.6f);input.tick(.02f);check(Math.abs(out.x-7f)<.001f,"Pointer uses scaled magnitude and elapsed seconds");
        input.tick(1);check(Math.abs(out.x-24.5f)<.001f,"Late tick is capped at 50 ms");
        input.tick(Float.NaN);input.tick(-1);check(Math.abs(out.x-24.5f)<.001f,"Invalid or negative tick cannot move pointer");
        input.axis("RightLeft","RightRight",0);input.axis("LeftLeft","LeftRight",.55f);check(!out.down.contains("KeyD"),"Normalized stick magnitude below press threshold stays neutral");
        input.axis("LeftLeft","LeftRight",.8f);check(out.down.contains("KeyD"),"Stick presses directional binding");
        input.axis("LeftLeft","LeftRight",.4f);check(out.down.contains("KeyD"),"Hysteresis avoids repeated threshold presses");
        input.axis("LeftLeft","LeftRight",.3f);check(!out.down.contains("KeyD"),"Stick releases below normalized release threshold");
        input.value("A",Float.NaN);input.value("A",Float.POSITIVE_INFINITY);input.value("unknown",1);check(out.down.isEmpty(),"Invalid source and nonfinite magnitude are ignored");
        input.activate(false);float old=out.x;input.value("R1",1);input.axis("RightLeft","RightRight",1);input.tick(.05f);
        check(out.down.isEmpty()&&out.x==old,"Disabled capture cannot produce inputs");
    }
    private static void rejects(Runnable operation){try{operation.run();throw new AssertionError("Invalid profile accepted");}catch(IllegalArgumentException expected){assertions++;}}
    private static void validation(){
        Recorder out=new Recorder();ControllerInput input=new ControllerInput(out);input.configure(ControllerInput.defaultLayers(),.2f,700);input.activate(true);input.selectLayer(1);input.value("X",1);
        Map<String,String> bad=ControllerInput.defaults();bad.put("A","Layer6");Map<String,String> invalidTarget=bad;rejects(()->input.configure(invalidTarget,.2f,700));
        check(input.currentLayer()==1&&out.down.contains("Digit8"),"Rejected profile leaves current selection and held input untouched");
        bad=ControllerInput.defaults();bad.put("A","Inherit");Map<String,String> invalidInherit=bad;rejects(()->input.configure(invalidInherit,.2f,700));
        bad=ControllerInput.defaults();bad.put("A","KeyUnknown");Map<String,String> invalidAction=bad;rejects(()->input.configure(invalidAction,.2f,700));
        bad=ControllerInput.defaults();bad.remove("R3");Map<String,String> missingSource=bad;rejects(()->input.configure(missingSource,.2f,700));
        rejects(()->input.configure(Collections.emptyList(),.2f,700));
        rejects(()->input.configure(Arrays.asList(new ControllerInput.Layer("Main",ControllerInput.defaults()),new ControllerInput.Layer("mAiN",ControllerInput.inherited())),.2f,700));
        rejects(()->input.configure(Collections.singletonList(new ControllerInput.Layer("bad\nname",ControllerInput.defaults())),.2f,700));
        rejects(()->input.configure(ControllerInput.defaultLayers(),Float.NaN,700));rejects(()->input.configure(ControllerInput.defaultLayers(),.01f,700));
        rejects(()->input.configure(ControllerInput.defaultLayers(),.2f,Float.POSITIVE_INFINITY));rejects(()->input.configure(ControllerInput.defaultLayers(),.2f,2501));
        rejects(()->input.selectLayer(-1));rejects(()->input.selectLayer(6));input.releaseAll();check(out.down.isEmpty(),"Profile rejection never compromises eventual release");
        List<ControllerInput.Layer> six=new ArrayList<>(ControllerInput.defaultLayers());six.add(new ControllerInput.Layer("Layer 5",ControllerInput.inherited()));six.add(new ControllerInput.Layer("Layer 6",ControllerInput.inherited()));
        input.configure(six,.05f,50);input.selectLayer(5);check(input.layerCount()==6&&input.currentLayer()==5,"Six layers and boundary settings are accepted");
        six.add(new ControllerInput.Layer("Layer 7",ControllerInput.inherited()));rejects(()->input.configure(six,.2f,700));
    }
    private static void randomizedTransitions(){
        Recorder out=new Recorder();ControllerInput input=new ControllerInput(out);input.configure(ControllerInput.defaultLayers(),.2f,700);input.activate(true);Random random=new Random(81819010);
        for(int i=0;i<10000;i++){
            int action=random.nextInt(16);
            if(action==0)input.activate(false);else if(action==1)input.activate(true);else if(action==2)input.releaseAll();else if(action==3)input.nextLayer();
            else if(action==4)input.axis("RightLeft","RightRight",random.nextFloat()*2-1);
            else {String source=ControllerInput.SOURCES.get(random.nextInt(ControllerInput.SOURCES.size()));input.value(source,random.nextBoolean()?1:0);}
            input.tick(.016f);
            check(input.currentLayer()>=0&&input.currentLayer()<4,"Randomized layer stays valid");
        }
        input.activate(false);check(out.down.isEmpty(),"Random focus, repeat, cycle and release sequence leaves no stuck input");
    }
    public static void main(String[] args){defaultsAndCycle();heldLayersAndChords();referenceCountsAndOneShots();analogMotion();validation();randomizedTransitions();System.out.println("PASS: controller defaults, layer/chord/mouse holds, hysteresis, motion bounds, profile rejection and 10,000 mixed transitions ("+assertions+" assertions)");}
}
