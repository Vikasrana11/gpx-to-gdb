from flask import Flask, request, send_file, jsonify, send_from_directory
from flask_cors import CORS
import os
import tempfile
import zipfile
from osgeo import ogr
import shutil
import sys

app = Flask(__name__, static_folder='static')
CORS(app, origins=["http://localhost:3000"])  # Restrict CORS to specific origins
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Limit uploads to 16MB

# Serve frontend
@app.route('/')
def serve_frontend():
    return send_from_directory('static', 'index.html')

# API endpoint for conversion
@app.route('/convert-to-gdb', methods=['POST'])
def convert_to_gdb():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    uploaded_file = request.files['file']
    if uploaded_file.filename == '' or not uploaded_file.filename.endswith('.gpx'):
        return jsonify({"error": "Invalid file: Please upload a .gpx file"}), 400

    temp_dir = None
    try:
        # Create temp directory
        temp_dir = tempfile.mkdtemp()
        gpx_path = os.path.join(temp_dir, "input.gpx")
        uploaded_file.save(gpx_path)

        # Create File Geodatabase
        gdb_name = os.path.splitext(uploaded_file.filename)[0] + ".gdb"
        gdb_path = os.path.join(temp_dir, gdb_name)
        
        # Convert using GDAL/OGR
        if not convert_gpx_to_gdb(gpx_path, gdb_path):
            return jsonify({"error": "Failed to convert GPX to GDB. Please ensure the file is valid."}), 500

        # Zip the GDB folder
        zip_path = os.path.join(temp_dir, gdb_name + ".zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(gdb_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arcname)

        return send_file(zip_path, as_attachment=True, download_name=gdb_name + ".zip")

    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

def convert_gpx_to_gdb(gpx_path, output_gdb):
    gpx_ds = None
    gdb_ds = None
    try:
        ogr.UseExceptions()
        
        if not os.path.exists(gpx_path):
            raise FileNotFoundError("GPX file not found")
            
        os.makedirs(os.path.dirname(output_gdb), exist_ok=True)
        
        driver = ogr.GetDriverByName("FileGDB")
        if driver is None:
            raise RuntimeError("FileGDB driver not available. Ensure GDAL is compiled with FileGDB support.")
            
        if os.path.exists(output_gdb):
            driver.DeleteDataSource(output_gdb)
            
        gdb_ds = driver.CreateDataSource(output_gdb)
        if gdb_ds is None:
            raise RuntimeError(f"Failed to create GDB at {output_gdb}")
        
        gpx_ds = ogr.Open(gpx_path)
        if gpx_ds is None:
            raise RuntimeError("Invalid GPX file")
            
        for i in range(gpx_ds.GetLayerCount()):
            layer = gpx_ds.GetLayerByIndex(i)
            if layer.GetFeatureCount() == 0:
                continue
                
            # Map GPX layer types to appropriate geometry types
            layer_name = layer.GetName()
            geom_type = layer.GetGeomType()
            out_layer = gdb_ds.CreateLayer(layer_name, geom_type=geom_type)
            
            if out_layer is None:
                continue
                
            layer_defn = layer.GetLayerDefn()
            for i in range(layer_defn.GetFieldCount()):
                out_layer.CreateField(layer_defn.GetFieldDefn(i))
                
            feature = layer.GetNextFeature()
            while feature:
                new_feature = ogr.Feature(out_layer.GetLayerDefn())
                new_feature.SetFrom(feature)
                out_layer.CreateFeature(new_feature)
                feature = layer.GetNextFeature()
                
        return True
        
    except Exception as e:
        print(f"Conversion error: {str(e)}", file=sys.stderr)
        return False
    finally:
        gpx_ds = None  # Ensure data sources are closed
        gdb_ds = None

if __name__ == '__main__':
    os.makedirs('static', exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=False)  # Disable debug in production